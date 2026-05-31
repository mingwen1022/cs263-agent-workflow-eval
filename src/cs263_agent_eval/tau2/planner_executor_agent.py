"""Planner-Executor workflow agent for tau2.

Architecture (2 LLM calls per turn max):
  Planner   — sees FULL conversation history + policy + tool schemas → outputs JSON plan
  Verifier  — lightweight, only gates write operations (no state tracking needed)
  Executor  — deterministic: validates args + constructs tau2 AssistantMessage

Key differences from the 4-node linear pipeline:
- No State Tracker: context loss is eliminated, Planner reasons from full history
- Planner = State Tracker + Reasoner merged, with the full context large_single uses
- Verifier is lighter: checks conversation history directly, not a fragile structured state
- Executor is purely deterministic (no LLM for tool calls)
"""

from __future__ import annotations

import copy
import json
import os
import re
import time
from typing import Any, Literal, Optional

from langchain_core.messages import (
    AIMessage, HumanMessage, SystemMessage, ToolMessage as LCToolMessage,
)
from langgraph.graph import END, START, StateGraph
from typing_extensions import TypedDict

from cs263_agent_eval.config import settings
from tau2.agent.base_agent import HalfDuplexAgent


TAU2_PE_AGENT_NAME = "planner_executor_agent"
MAX_VERIFIER_RETRIES = 2
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

# ─── Prompts ──────────────────────────────────────────────────────────────────

_PLANNER_SYSTEM = """\
You are a customer service agent for a retail company.
Given the full conversation history, decide the agent's next action.
Output ONLY a JSON object — no text outside the JSON.

Output format:
{{
  "type": "ask_user | call_tool | write_tool | final_reply",
  "reason": "brief reason for this action",
  "tool": "exact tool name (only for call_tool/write_tool)",
  "tool_args": {{"param": value}},
  "text_content": "what to say to the user (only for ask_user/final_reply)",
  "requires_verification": true or false
}}

Decision rules:
1. If user is not yet authenticated (no successful user ID lookup in history) → ask_user.
2. If task intent is unclear → ask_user to clarify.
3. If user is authenticated but order details not yet fetched → call_tool get_user_details or get_order_details.
4. If order and product details are available → propose write_tool or ask_user for confirmation.
5. If all goals are completed → final_reply.

Hard rules:
- requires_verification=true for write_tool and final_reply; false for ask_user and call_tool.
- Include ALL items the user mentioned in ONE write_tool call — never split.
- Order IDs must use "#" prefix (e.g., "#W2378156").
- For product variant selection: look at the product variants in tool results and select the best match for the user's stated preference (size, color, features). Do NOT call get_product_details again if you already have the variants.
- For return/exchange: payment_method_id comes from the order details you already retrieved (the original payment method).
- transfer_to_human_agents: ONLY if user explicitly asks for a human agent or the request is truly impossible by policy. Never because a tool lookup failed.

Policy:
{policy}\
""".strip()

_VERIFIER_SYSTEM = """\
You verify a proposed write action before it is executed.
Output ONLY a JSON object — no text outside the JSON.

Output format:
{{
  "approved": true or false,
  "blocking_issues": ["issue 1", "issue 2"],
  "required_fix": "what must be corrected, or null if approved"
}}

Given the conversation summary and proposed action, check ALL of:
1. User authentication: a user ID lookup tool was successfully called in the conversation.
2. Order status: delivered for exchange/return; pending for cancel/modify.
3. No duplicate: this exact write operation was NOT already executed in this conversation.
4. Argument correctness: item_ids are item IDs from order details, not product IDs.
5. Completeness: ALL items the user mentioned are included in the call.
6. Payment method: payment_method_id is present (not null) when required.
7. Policy compliance: the action complies with the retail policy.

For final_reply: check that all stated user goals have been completed.

If any check fails → approved=false with specific blocking_issues.
If all pass → approved=true, blocking_issues=[].\
""".strip()


# ─── LangGraph per-turn state ─────────────────────────────────────────────────

class TurnState(TypedDict, total=False):
    lc_messages: list          # full conversation in LangChain format
    tool_descriptions: str
    policy: str
    turn_count: int
    conv_summary: str          # compact summary for Verifier

    proposal: dict
    verifier_feedback: dict
    retry_count: int

    action_type: str
    action_content: str
    action_tool_name: str
    action_tool_args: dict


# ─── Persistent agent state ───────────────────────────────────────────────────

class PlannerExecutorState:
    def __init__(
        self,
        messages: list[Any],
        turn_count: int = 0,
        write_counts: Optional[dict[str, int]] = None,
    ) -> None:
        self.messages = messages
        self.turn_count = turn_count
        self.write_counts: dict[str, int] = write_counts or {}


# ─── Helpers ──────────────────────────────────────────────────────────────────

def _parse_json(text: str) -> dict | None:
    if not text:
        return None
    text = text.strip()
    for pattern in (
        r"```json\s*(\{.*?\})\s*```",
        r"```\s*(\{.*?\})\s*```",
        r"(\{.*\})",
    ):
        m = re.search(pattern, text, re.DOTALL)
        if m:
            try:
                return json.loads(m.group(1))
            except json.JSONDecodeError:
                continue
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return None


def _content_to_text(content: Any) -> str:
    if content is None:
        return ""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = [str(item.get("text", "")) if isinstance(item, dict) else str(item)
                 for item in content]
        return "\n".join(p for p in parts if p)
    return str(content)


# ─── PlannerExecutorTau2Agent ─────────────────────────────────────────────────

class PlannerExecutorTau2Agent(HalfDuplexAgent[PlannerExecutorState]):
    """Planner-Executor tau2 agent with full-context Planner and lightweight Verifier."""

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
        self._raw_schemas = [tool.openai_schema for tool in tools]
        self._valid_params = {
            s.get("function", s).get("name", ""): set(
                s.get("function", s).get("parameters", {}).get("properties", {}).keys()
            )
            for s in self._raw_schemas
        }
        self._known_tool_names = set(self._valid_params.keys())
        self._tool_descriptions = self._build_tool_descriptions()
        self._graph = self._build_graph()

    # ── Model ─────────────────────────────────────────────────────────────────

    def _build_model(self):
        if self.llm.startswith("ollama/"):
            from langchain_ollama import ChatOllama
            model_name = self.llm.removeprefix("ollama/")
            kwargs: dict[str, Any] = {"model": model_name}
            if self.llm_args.get("temperature") is not None:
                kwargs["temperature"] = self.llm_args["temperature"]
            return ChatOllama(**kwargs)

        from langchain_google_vertexai import ChatVertexAI
        model_name = self.llm.removeprefix("vertex_ai/")
        kwargs = {
            "model": model_name,
            "project": settings.project_id or os.getenv("VERTEXAI_PROJECT"),
            "location": os.getenv("VERTEXAI_LOCATION") or settings.location,
            "temperature": self.llm_args.get("temperature", settings.temperature),
            "max_tokens": self.llm_args.get("max_tokens"),
        }
        return ChatVertexAI(**{k: v for k, v in kwargs.items() if v is not None})

    def _build_tool_descriptions(self) -> str:
        lines = []
        for schema in self._raw_schemas:
            fn = schema.get("function", schema)
            name = fn.get("name", "")
            desc = fn.get("description", "").split("\n")[0]
            params = fn.get("parameters", {})
            props = params.get("properties", {})
            required = set(params.get("required", []))
            parts = [f"{p}{'*' if p in required else ''}:{ps.get('type','any')}"
                     for p, ps in props.items()]
            lines.append(f"- {name}({', '.join(parts)}): {desc}")
        return "\n".join(lines)

    # ── tau2 interface ─────────────────────────────────────────────────────────

    def get_init_state(
        self, message_history: Optional[list[Any]] = None
    ) -> PlannerExecutorState:
        from tau2.agent.base_agent import is_valid_agent_history_message
        if message_history is None:
            message_history = []
        assert all(is_valid_agent_history_message(m) for m in message_history)
        return PlannerExecutorState(messages=list(message_history))

    def generate_next_message(
        self, message: Any, state: PlannerExecutorState
    ) -> tuple[Any, PlannerExecutorState]:
        from tau2.data_model.message import AssistantMessage, MultiToolMessage, ToolCall

        if isinstance(message, MultiToolMessage):
            state.messages.extend(message.tool_messages)
        else:
            state.messages.append(message)

        state.turn_count += 1
        started = time.perf_counter()

        # P0: hard write-loop guard
        overloaded = [t for t, c in state.write_counts.items() if c >= MAX_WRITE_CALLS]
        if overloaded:
            generation_seconds = time.perf_counter() - started
            msg = AssistantMessage(
                role="assistant",
                content="I've completed the available modifications. Is there anything else I can help you with?",
                tool_calls=None, cost=0.0, usage=None,
                raw_data={"pe": True, "p0_guard": overloaded},
                generation_time_seconds=generation_seconds,
            )
            state.messages.append(msg)
            return msg, state

        lc_messages = self._to_lc_messages(state.messages)
        conv_summary = self._build_conv_summary(state.messages)

        turn_input: TurnState = {
            "lc_messages": lc_messages,
            "tool_descriptions": self._tool_descriptions,
            "policy": self.domain_policy,
            "turn_count": state.turn_count,
            "conv_summary": conv_summary,
            "retry_count": 0,
        }

        result: TurnState = self._graph.invoke(turn_input, config={"recursion_limit": 20})
        generation_seconds = time.perf_counter() - started

        action_type = result.get("action_type", "text")
        if action_type == "tool_call":
            tool_name = result.get("action_tool_name", "")
            tool_args = result.get("action_tool_args", {})
            call_id = f"pe_{state.turn_count}_0"

            if tool_name in WRITE_TOOLS:
                state.write_counts[tool_name] = state.write_counts.get(tool_name, 0) + 1

            assistant_message = AssistantMessage(
                role="assistant", content=None,
                tool_calls=[ToolCall(id=call_id, name=tool_name, arguments=tool_args)],
                cost=0.0, usage=None,
                raw_data={"pe": True, "proposal": result.get("proposal", {})},
                generation_time_seconds=generation_seconds,
            )
        else:
            content = result.get("action_content") or "How can I help you?"
            assistant_message = AssistantMessage(
                role="assistant", content=content, tool_calls=None,
                cost=0.0, usage=None,
                raw_data={"pe": True, "proposal": result.get("proposal", {})},
                generation_time_seconds=generation_seconds,
            )

        state.messages.append(assistant_message)
        return assistant_message, state

    def stop(self, message: Any = None, state: Any = None) -> None:
        return None

    def set_seed(self, seed: int) -> None:
        self.llm_args["seed"] = seed
        self._model = self._build_model()

    # ── Message conversion ─────────────────────────────────────────────────────

    def _to_lc_messages(self, messages: list[Any]) -> list:
        from tau2.data_model.message import AssistantMessage, ToolMessage, UserMessage

        converted = []
        for msg in messages:
            if isinstance(msg, UserMessage):
                converted.append(HumanMessage(content=msg.content or ""))
            elif isinstance(msg, AssistantMessage):
                tool_calls = [
                    {"name": tc.name, "args": tc.arguments, "id": tc.id}
                    for tc in (msg.tool_calls or [])
                ]
                converted.append(AIMessage(content=msg.content or "", tool_calls=tool_calls))
            elif isinstance(msg, ToolMessage):
                converted.append(LCToolMessage(content=msg.content or "", tool_call_id=msg.id))
        return converted

    def _build_conv_summary(self, messages: list[Any]) -> str:
        """Build a compact conversation summary for Verifier context."""
        from tau2.data_model.message import AssistantMessage, ToolMessage, UserMessage

        lines = []
        pending_calls: dict[str, str] = {}

        for msg in messages:
            if isinstance(msg, AssistantMessage):
                for tc in (msg.tool_calls or []):
                    pending_calls[tc.id] = tc.name
                    if tc.name in WRITE_TOOLS:
                        lines.append(f"WRITE_PROPOSED: {tc.name}({json.dumps(tc.arguments)[:120]})")
            elif isinstance(msg, ToolMessage):
                tool_name = pending_calls.get(msg.id, "unknown")
                content = (msg.content or "")[:150]
                if "Error" in content:
                    lines.append(f"TOOL_ERROR: {tool_name} → {content[:80]}")
                elif tool_name in WRITE_TOOLS:
                    lines.append(f"WRITE_EXECUTED: {tool_name} → success")
                elif tool_name in ("find_user_id_by_name_zip", "find_user_id_by_email"):
                    lines.append(f"AUTH: user_id={content.strip()[:40]}")
                elif tool_name == "get_order_details":
                    try:
                        d = json.loads(content)
                        lines.append(f"ORDER: {d.get('order_id')} status={d.get('status')} pay={d.get('payment_method_id','?')}")
                    except Exception:
                        lines.append(f"ORDER_RESULT: {content[:80]}")
            elif isinstance(msg, UserMessage):
                lines.append(f"USER: {(msg.content or '')[:100]}")

        return "\n".join(lines) if lines else "No significant events yet."

    # ── LangGraph graph ────────────────────────────────────────────────────────

    def _build_graph(self):
        valid_params = self._valid_params
        known_tools = self._known_tool_names

        # ── Planner ───────────────────────────────────────────────────────
        def planner_node(state: TurnState) -> dict:
            system = _PLANNER_SYSTEM.format(policy=state["policy"])

            # Add tool descriptions + turn count as context
            context_msg = (
                f"turn: {state.get('turn_count', 0)}\n\n"
                f"Available tools:\n{state['tool_descriptions']}"
            )
            feedback = state.get("verifier_feedback")
            if feedback and not feedback.get("approved", True):
                issues = "\n".join(f"- {i}" for i in feedback.get("blocking_issues", []))
                prev = json.dumps(state.get("proposal", {}), indent=2)
                context_msg += (
                    f"\n\nVerifier rejected previous proposal:\n{issues}"
                    f"\nRequired fix: {feedback.get('required_fix', '')}"
                    f"\nPrevious proposal:\n{prev}"
                )

            messages = [
                SystemMessage(content=system),
                *state["lc_messages"],
                HumanMessage(content=context_msg),
            ]
            response = self._model.invoke(messages)
            parsed = _parse_json(_content_to_text(response.content))
            if not parsed or "type" not in parsed:
                parsed = {
                    "type": "ask_user",
                    "reason": "Could not determine next action",
                    "text_content": "Could you please clarify what you need?",
                    "requires_verification": False,
                }
            return {"proposal": parsed}

        # ── Verifier ──────────────────────────────────────────────────────
        def verifier_node(state: TurnState) -> dict:
            proposal = state.get("proposal", {})
            prompt = (
                f"Conversation summary:\n{state['conv_summary']}\n\n"
                f"Proposed action:\n{json.dumps(proposal, indent=2)}\n\n"
                f"Policy:\n{state['policy']}"
            )
            response = self._model.invoke([
                SystemMessage(content=_VERIFIER_SYSTEM),
                HumanMessage(content=prompt),
            ])
            parsed = _parse_json(_content_to_text(response.content))
            if not parsed or "approved" not in parsed:
                parsed = {"approved": True, "blocking_issues": [], "required_fix": None}
            return {"verifier_feedback": parsed}

        # ── Executor ──────────────────────────────────────────────────────
        def executor_node(state: TurnState) -> dict:
            proposal = state.get("proposal", {})
            action_type = proposal.get("type", "ask_user")

            if action_type in ("call_tool", "write_tool"):
                tool_name = proposal.get("tool", "")
                if tool_name not in known_tools:
                    return {
                        "action_type": "text",
                        "action_content": "Let me look into that for you.",
                    }
                raw_args = proposal.get("tool_args", {})
                clean_args = {k: v for k, v in raw_args.items()
                              if k in valid_params.get(tool_name, set())}
                return {
                    "action_type": "tool_call",
                    "action_tool_name": tool_name,
                    "action_tool_args": clean_args,
                }

            # Text output (ask_user or final_reply)
            return {
                "action_type": "text",
                "action_content": proposal.get("text_content") or "How can I help you?",
            }

        # ── Bump retry ────────────────────────────────────────────────────
        def bump_retry_node(state: TurnState) -> dict:
            return {"retry_count": state.get("retry_count", 0) + 1}

        # ── Safe fallback ─────────────────────────────────────────────────
        def safe_fallback_node(state: TurnState) -> dict:
            return {
                "action_type": "text",
                "action_content": (
                    "I want to make sure I handle your request correctly. "
                    "Could you please confirm what you'd like me to do?"
                ),
            }

        # ── Routing ───────────────────────────────────────────────────────
        def route_after_planner(
            state: TurnState,
        ) -> Literal["verifier", "executor"]:
            if state.get("proposal", {}).get("requires_verification", False):
                return "verifier"
            return "executor"

        def route_after_verifier(
            state: TurnState,
        ) -> Literal["executor", "bump_retry", "safe_fallback"]:
            feedback = state.get("verifier_feedback", {})
            if feedback.get("approved", True):
                return "executor"
            if state.get("retry_count", 0) < MAX_VERIFIER_RETRIES:
                return "bump_retry"
            return "safe_fallback"

        # ── Build graph ───────────────────────────────────────────────────
        graph = StateGraph(TurnState)
        graph.add_node("planner", planner_node)
        graph.add_node("verifier", verifier_node)
        graph.add_node("executor", executor_node)
        graph.add_node("bump_retry", bump_retry_node)
        graph.add_node("safe_fallback", safe_fallback_node)

        graph.add_edge(START, "planner")
        graph.add_conditional_edges(
            "planner",
            route_after_planner,
            {"verifier": "verifier", "executor": "executor"},
        )
        graph.add_conditional_edges(
            "verifier",
            route_after_verifier,
            {"executor": "executor", "bump_retry": "bump_retry", "safe_fallback": "safe_fallback"},
        )
        graph.add_edge("bump_retry", "planner")
        graph.add_edge("executor", END)
        graph.add_edge("safe_fallback", END)

        return graph.compile()


# ─── Factory + registration ───────────────────────────────────────────────────

def create_planner_executor_agent(
    tools: list[Any],
    domain_policy: str,
    llm: str,
    llm_args: Optional[dict[str, Any]] = None,
    **_: Any,
) -> PlannerExecutorTau2Agent:
    return PlannerExecutorTau2Agent(
        tools=tools, domain_policy=domain_policy, llm=llm, llm_args=llm_args,
    )


def register_planner_executor_agent() -> None:
    from tau2.registry import registry
    if registry.get_agent_factory(TAU2_PE_AGENT_NAME) is None:
        registry.register_agent_factory(
            create_planner_executor_agent,
            TAU2_PE_AGENT_NAME,
        )
