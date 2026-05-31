"""SMAG (State Machine Augmented Generation) tau2 agent.

Key idea: replace LLM-based state tracking with a deterministic Python state machine.
The state machine:
  - Parses tool results to maintain ground-truth state (authenticated, orders, writes done)
  - Provides structured context to the LLM in every system prompt
  - Enforces preconditions before any write operation (deterministic, no hallucination)

Architecture per turn:
  1. Python StateMachine.update() — parse incoming tool result, update state
  2. LLM (full context + state machine summary) — generate next action
  3. If write tool proposed: StateMachine.can_execute() — deterministic precondition check
  4. If rejected (≤2 retries): re-invoke LLM with rejection reason injected
  5. Executor — validate args against schema, return tau2 AssistantMessage
"""

from __future__ import annotations

import json
import os
import re
import time
from dataclasses import dataclass, field
from typing import Any, Optional

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage
from langchain_core.messages import ToolMessage as LCToolMessage

from cs263_agent_eval.config import settings
from tau2.agent.base_agent import HalfDuplexAgent


TAU2_SMAG_AGENT_NAME = "smag_agent"
MAX_WRITE_RETRIES = 2
MAX_WRITE_CALLS = 3

WRITE_TOOLS = {
    "exchange_delivered_order_items",
    "return_delivered_order_items",
    "cancel_pending_order",
    "modify_pending_order",
    "modify_pending_order_address",
    "modify_pending_order_payment",
    "modify_pending_order_items",
    "modify_user_address",
    "transfer_to_human_agents",
}

# ─── State Machine ────────────────────────────────────────────────────────────

@dataclass
class OrderState:
    order_id: str
    status: str = ""
    payment_method_id: str = ""
    items: dict = field(default_factory=dict)  # item_id -> {product_id, name, status}


@dataclass
class RetailStateMachine:
    """Deterministic state tracker. Updated by parsing tool results, never by LLM."""

    authenticated: bool = False
    user_id: Optional[str] = None
    orders: dict = field(default_factory=dict)       # order_id -> OrderState
    completed_writes: list = field(default_factory=list)  # [{tool, order_id, turn}]
    error_log: list = field(default_factory=list)    # tool call errors
    known_variant_ids: set = field(default_factory=set)  # Fix 1: valid variant IDs from product details

    # ── Update from tool results ─────────────────────────────────────────────

    def update(self, tool_name: str, tool_args: dict, result_text: str, turn: int) -> None:
        """Parse a tool result and update state. Fully deterministic."""
        if not result_text or "Error" in result_text:
            self.error_log.append({"tool": tool_name, "error": result_text[:120], "turn": turn})
            return

        if tool_name in ("find_user_id_by_name_zip", "find_user_id_by_email"):
            uid = result_text.strip().split("\n")[0].strip()
            if uid and not uid.startswith("{"):
                self.user_id = uid
                self.authenticated = True

        elif tool_name == "get_user_details":
            try:
                d = json.loads(result_text)
                # Extract order IDs from user profile
                for order in d.get("orders", []):
                    oid = order if isinstance(order, str) else order.get("order_id", "")
                    if oid and oid not in self.orders:
                        self.orders[oid] = OrderState(order_id=oid)
            except (json.JSONDecodeError, TypeError):
                pass

        elif tool_name == "get_order_details":
            try:
                d = json.loads(result_text)
                oid = d.get("order_id", tool_args.get("order_id", ""))
                if oid:
                    os_obj = self.orders.get(oid) or OrderState(order_id=oid)
                    os_obj.status = d.get("status", "")
                    os_obj.payment_method_id = d.get("payment_method_id", "")
                    for item in d.get("items", []):
                        iid = item.get("item_id", "")
                        if iid:
                            os_obj.items[iid] = {
                                "product_id": item.get("product_id", ""),
                                "name": item.get("name", ""),
                            }
                    self.orders[oid] = os_obj
            except (json.JSONDecodeError, TypeError):
                pass

        elif tool_name == "get_product_details":
            try:
                d = json.loads(result_text)
                for vid in d.get("variants", {}).keys():
                    self.known_variant_ids.add(vid)
            except (json.JSONDecodeError, TypeError):
                pass

        elif tool_name in WRITE_TOOLS:
            order_id = tool_args.get("order_id", "")
            self.completed_writes.append({
                "tool": tool_name, "order_id": order_id,
                "args": tool_args, "turn": turn,
            })
            if tool_name == "transfer_to_human_agents":
                pass  # conversation will end

    # ── Precondition checking ─────────────────────────────────────────────────

    def can_execute(self, tool_name: str, tool_args: dict) -> tuple[bool, list[str]]:
        """Check preconditions before executing a write operation. Returns (ok, issues)."""
        if tool_name == "transfer_to_human_agents":
            return True, []

        issues = []

        # 1. Authentication
        if not self.authenticated:
            issues.append("User is not authenticated — call find_user_id first")

        # 2. No duplicate write for same order
        order_id = tool_args.get("order_id", "")
        for w in self.completed_writes:
            if w["tool"] == tool_name and w["order_id"] == order_id:
                issues.append(
                    f"{tool_name} was already executed on {order_id} at turn {w['turn']}"
                )

        # 3. Order status
        if order_id:
            order = self.orders.get(order_id)
            if order:
                delivered_ops = {
                    "exchange_delivered_order_items",
                    "return_delivered_order_items",
                }
                pending_ops = {
                    "cancel_pending_order",
                    "modify_pending_order",
                    "modify_pending_order_address",
                    "modify_pending_order_payment",
                    "modify_pending_order_items",
                }
                if tool_name in delivered_ops and order.status != "delivered":
                    issues.append(
                        f"Order {order_id} status is '{order.status}', need 'delivered'"
                    )
                if tool_name in pending_ops and order.status != "pending":
                    issues.append(
                        f"Order {order_id} status is '{order.status}', need 'pending'"
                    )

                # 4. item_ids must be actual item IDs from the order
                item_ids = tool_args.get("item_ids", [])
                if item_ids and order.items:
                    known_ids = set(order.items.keys())
                    bad = [i for i in item_ids if i not in known_ids]
                    if bad:
                        issues.append(
                            f"item_ids {bad} not found in order {order_id}. "
                            f"Valid item_ids: {list(known_ids)}"
                        )
            else:
                issues.append(
                    f"Order {order_id} details not yet fetched — call get_order_details first"
                )

        # 5. payment_method_id present when needed
        needs_payment = {
            "exchange_delivered_order_items",
            "return_delivered_order_items",
        }
        if tool_name in needs_payment and not tool_args.get("payment_method_id"):
            issues.append("payment_method_id is required but missing")

        # 6. Fix 1: new_item_ids must be valid product variant IDs (from get_product_details)
        if tool_name == "exchange_delivered_order_items" and self.known_variant_ids:
            new_ids = tool_args.get("new_item_ids", [])
            bad_new = [i for i in new_ids if i not in self.known_variant_ids]
            if bad_new:
                issues.append(
                    f"new_item_ids {bad_new} are not valid product variant IDs. "
                    f"Call get_product_details to find valid replacement variants."
                )

        return len(issues) == 0, issues

    # ── Summary for LLM ───────────────────────────────────────────────────────

    def to_context(self) -> str:
        """Compact state summary to inject into LLM system prompt."""
        lines = ["<state_machine>"]

        if self.authenticated:
            lines.append(f"authenticated: true (user_id: {self.user_id})")
        else:
            lines.append("authenticated: false")

        if self.orders:
            lines.append("orders:")
            for oid, o in self.orders.items():
                pay = o.payment_method_id or "unknown"
                lines.append(f"  {oid}: status={o.status or '?'}, payment={pay}")
                for iid, info in list(o.items.items())[:8]:
                    lines.append(f"    item {iid}: {info.get('name', '?')}")

        if self.known_variant_ids:
            lines.append(f"product_variants_fetched: {len(self.known_variant_ids)} valid variant IDs known")

        if self.completed_writes:
            lines.append("completed_writes:")
            for w in self.completed_writes:
                lines.append(f"  turn {w['turn']}: {w['tool']} on {w['order_id']}")
        else:
            lines.append("completed_writes: none")

        if self.error_log:
            lines.append("recent_errors:")
            for e in self.error_log[-3:]:
                lines.append(f"  {e['tool']}: {e['error'][:80]}")

        lines.append("</state_machine>")
        return "\n".join(lines)


# ─── Agent State ──────────────────────────────────────────────────────────────

class SMAGAgentState:
    def __init__(
        self,
        messages: list[Any],
        state_machine: Optional[RetailStateMachine] = None,
        turn_count: int = 0,
        write_counts: Optional[dict[str, int]] = None,
    ) -> None:
        self.messages = messages
        self.state_machine = state_machine or RetailStateMachine()
        self.turn_count = turn_count
        self.write_counts: dict[str, int] = write_counts or {}


# ─── Helpers ──────────────────────────────────────────────────────────────────

def _content_to_text(content: Any) -> str:
    if content is None:
        return ""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = [str(i.get("text", "")) if isinstance(i, dict) else str(i) for i in content]
        return "\n".join(p for p in parts if p)
    return str(content)


# ─── System Prompt ────────────────────────────────────────────────────────────

_SYSTEM_TEMPLATE = """\
You are a retail customer service agent.
Help the user with their order using the available tools.
Follow the policy strictly.

{state_context}

Rules:
- Authenticate the user before any account action (call find_user_id_by_name_zip or find_user_id_by_email)
- Look up order details before proposing exchanges/returns/cancels
- For product exchanges: look up product details to select the right variant based on user preference
- Include ALL requested items in ONE write call — never split across multiple calls
- Order IDs must use "#" prefix (e.g., "#W2378156")
- payment_method_id for returns/exchanges: use the one from get_order_details
- transfer_to_human_agents: only if user explicitly asks or the request violates policy
- get_product_details only accepts product_id — do NOT pass extra kwargs

Direct execution rule: Once you have collected ALL required information (authenticated, order details fetched, product variants looked up if needed), call the write tool directly — do not ask "Shall I proceed?" as a separate message. The user's initial request is sufficient authorization. However, do NOT execute prematurely — first complete all necessary lookups, then execute.

Final response rule: After completing operations, answer ALL questions the user asked during the conversation (e.g., product option counts, prices, availability), not just confirm what was done.

Policy:
{policy}\
"""


# ─── SMAGAgent ────────────────────────────────────────────────────────────────

class SMAGAgent(HalfDuplexAgent[SMAGAgentState]):
    """SMAG agent: deterministic state machine + full-context LLM + deterministic prechecks."""

    def __init__(
        self,
        tools: list[Any],
        domain_policy: str,
        llm: str,
        llm_args: Optional[dict[str, Any]] = None,
    ) -> None:
        super().__init__(tools=tools, domain_policy=domain_policy)
        self.tools = tools
        self.domain_policy = domain_policy
        self.llm = llm
        self.llm_args = dict(llm_args or {})
        self._model = self._build_model()
        self._raw_schemas = [t.openai_schema for t in tools]
        self._valid_params: dict[str, set[str]] = {
            s.get("function", s).get("name", ""): set(
                s.get("function", s).get("parameters", {}).get("properties", {}).keys()
            )
            for s in self._raw_schemas
        }
        self._bound_model = self._model.bind_tools(self._raw_schemas)

    # ── Model ─────────────────────────────────────────────────────────────────

    def _build_model(self):
        if self.llm.startswith("ollama/"):
            from langchain_ollama import ChatOllama
            kwargs: dict[str, Any] = {"model": self.llm.removeprefix("ollama/")}
            if self.llm_args.get("temperature") is not None:
                kwargs["temperature"] = self.llm_args["temperature"]
            return ChatOllama(**kwargs)

        from langchain_google_vertexai import ChatVertexAI
        kwargs = {
            "model": self.llm.removeprefix("vertex_ai/"),
            "project": settings.project_id or os.getenv("VERTEXAI_PROJECT"),
            "location": os.getenv("VERTEXAI_LOCATION") or settings.location,
            "temperature": self.llm_args.get("temperature", settings.temperature),
            "max_tokens": self.llm_args.get("max_tokens"),
        }
        return ChatVertexAI(**{k: v for k, v in kwargs.items() if v is not None})

    # ── tau2 interface ─────────────────────────────────────────────────────────

    def get_init_state(
        self, message_history: Optional[list[Any]] = None
    ) -> SMAGAgentState:
        from tau2.agent.base_agent import is_valid_agent_history_message
        if message_history is None:
            message_history = []
        assert all(is_valid_agent_history_message(m) for m in message_history)
        return SMAGAgentState(messages=list(message_history))

    def generate_next_message(
        self, message: Any, state: SMAGAgentState
    ) -> tuple[Any, SMAGAgentState]:
        from tau2.data_model.message import AssistantMessage, MultiToolMessage, ToolCall, ToolMessage

        # Append incoming message
        if isinstance(message, MultiToolMessage):
            state.messages.extend(message.tool_messages)
            tool_msgs = message.tool_messages
        else:
            state.messages.append(message)
            tool_msgs = [message] if isinstance(message, ToolMessage) else []

        state.turn_count += 1
        started = time.perf_counter()

        # ── Update state machine from tool results ────────────────────────
        for tmsg in tool_msgs:
            tool_name, tool_args = self._find_tool_call(state.messages, tmsg.id)
            if tool_name:
                state.state_machine.update(tool_name, tool_args, tmsg.content or "", state.turn_count)

        # ── P0: hard write-loop guard ─────────────────────────────────────
        overloaded = [t for t, c in state.write_counts.items() if c >= MAX_WRITE_CALLS]
        if overloaded:
            gen_s = time.perf_counter() - started
            msg = AssistantMessage(
                role="assistant",
                content="I've completed the available modifications. Is there anything else I can help you with?",
                tool_calls=None, cost=0.0, usage=None,
                raw_data={"smag": True, "p0_guard": overloaded},
                generation_time_seconds=gen_s,
            )
            state.messages.append(msg)
            return msg, state

        # ── LLM call with retry on write rejection ────────────────────────
        rejection_context = ""
        for attempt in range(MAX_WRITE_RETRIES + 1):
            system_content = _SYSTEM_TEMPLATE.format(
                state_context=state.state_machine.to_context(),
                policy=self.domain_policy,
            )
            if rejection_context:
                system_content += f"\n\nPRECONDITION FAILURE on previous proposal:\n{rejection_context}\nPlease revise your action."

            lc_messages = [SystemMessage(content=system_content)]
            lc_messages.extend(self._to_lc_messages(state.messages))

            ai_msg = self._bound_model.invoke(lc_messages)
            tool_calls = getattr(ai_msg, "tool_calls", None) or []

            # Check write tools with state machine
            rejected = False
            for tc in tool_calls:
                if tc["name"] not in WRITE_TOOLS:
                    continue
                clean_args = {k: v for k, v in (tc.get("args") or {}).items()
                              if k in self._valid_params.get(tc["name"], set())}
                ok, issues = state.state_machine.can_execute(tc["name"], clean_args)
                if not ok:
                    rejection_context = "\n".join(f"- {i}" for i in issues)
                    rejected = True
                    break

            if not rejected:
                break
            # else: retry with rejection context

        # ── Build tau2 AssistantMessage ───────────────────────────────────
        generation_seconds = time.perf_counter() - started
        tau2_tool_calls = []
        for tc in tool_calls:
            name = tc["name"]
            clean_args = {k: v for k, v in (tc.get("args") or {}).items()
                          if k in self._valid_params.get(name, set())}
            call_id = tc.get("id") or f"smag_{state.turn_count}_{len(tau2_tool_calls)}"
            tau2_tool_calls.append(ToolCall(id=call_id, name=name, arguments=clean_args))
            if name in WRITE_TOOLS:
                state.write_counts[name] = state.write_counts.get(name, 0) + 1

        if tau2_tool_calls:
            assistant_message = AssistantMessage(
                role="assistant", content=None,
                tool_calls=tau2_tool_calls, cost=0.0, usage=None,
                raw_data={"smag": True},
                generation_time_seconds=generation_seconds,
            )
        else:
            content = _content_to_text(ai_msg.content) or "How can I help you?"
            assistant_message = AssistantMessage(
                role="assistant", content=content, tool_calls=None,
                cost=0.0, usage=None,
                raw_data={"smag": True},
                generation_time_seconds=generation_seconds,
            )

        state.messages.append(assistant_message)
        return assistant_message, state

    def stop(self, message: Any = None, state: Any = None) -> None:
        return None

    def set_seed(self, seed: int) -> None:
        self.llm_args["seed"] = seed
        self._model = self._build_model()
        self._bound_model = self._model.bind_tools(self._raw_schemas)

    # ── Helpers ───────────────────────────────────────────────────────────────

    def _find_tool_call(
        self, messages: list[Any], tool_call_id: str
    ) -> tuple[str, dict]:
        """Find the tool name and args for a given tool_call_id in message history."""
        from tau2.data_model.message import AssistantMessage as Tau2AssistantMsg
        for msg in reversed(messages):
            if not isinstance(msg, Tau2AssistantMsg):
                continue
            for tc in (msg.tool_calls or []):
                if tc.id == tool_call_id:
                    return tc.name, tc.arguments
        return "", {}

    def _to_lc_messages(self, messages: list[Any]) -> list:
        from tau2.data_model.message import AssistantMessage as Tau2Asst, ToolMessage, UserMessage
        converted = []
        for msg in messages:
            if isinstance(msg, UserMessage):
                converted.append(HumanMessage(content=msg.content or ""))
            elif isinstance(msg, Tau2Asst):
                tcs = [{"name": tc.name, "args": tc.arguments, "id": tc.id}
                       for tc in (msg.tool_calls or [])]
                converted.append(AIMessage(content=msg.content or "", tool_calls=tcs))
            elif isinstance(msg, ToolMessage):
                converted.append(LCToolMessage(content=msg.content or "", tool_call_id=msg.id))
        return converted


# ─── Factory + registration ───────────────────────────────────────────────────

def create_smag_agent(
    tools: list[Any],
    domain_policy: str,
    llm: str,
    llm_args: Optional[dict[str, Any]] = None,
    **_: Any,
) -> SMAGAgent:
    return SMAGAgent(tools=tools, domain_policy=domain_policy, llm=llm, llm_args=llm_args)


def register_smag_agent() -> None:
    from tau2.registry import registry
    if registry.get_agent_factory(TAU2_SMAG_AGENT_NAME) is None:
        registry.register_agent_factory(create_smag_agent, TAU2_SMAG_AGENT_NAME)
