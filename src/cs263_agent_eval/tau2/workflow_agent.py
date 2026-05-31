"""4-node workflow tau2 agent (v2).

Pipeline per turn: State Tracker → Reasoner → (Verifier) → Action Generator
Each generate_next_message() call runs the graph once and returns ONE AssistantMessage.
Structured state persists across turns in WorkflowTau2AgentState.

v2 fixes:
- P0: hard write-repetition guard in Python before LangGraph runs
- P1: tool name validation in action_generator_node
- P2: State Tracker tracks terminal tools + unanswered questions
- P3: Verifier checks duplicate writes and payment_method_id policy
- P4: Reasoner is turn-count aware, forced final_reply after limit
- P5: Action Generator covers all unanswered user questions in final_reply
"""

from __future__ import annotations

import copy
import json
import os
import re
import time
from typing import Any, Literal, Optional

from langchain_core.messages import HumanMessage, SystemMessage
from langgraph.graph import END, START, StateGraph
from typing_extensions import TypedDict

from cs263_agent_eval.config import settings
from tau2.agent.base_agent import HalfDuplexAgent


TAU2_WORKFLOW_AGENT_NAME = "workflow_agent"
MAX_VERIFIER_RETRIES = 2
MAX_WRITE_CALLS = 3      # hard cap per write tool per conversation
MAX_READ_CALLS = 8       # hard cap per read tool per conversation (prevents read loops)
MAX_TURNS = 30           # force final_reply after this many turns

# Write tools that cannot be repeated for the same order
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

# ─── Empty structured state ───────────────────────────────────────────────────

EMPTY_STRUCTURED_STATE: dict[str, Any] = {
    "user_identity": {
        "authenticated": False,
        "user_id": None,
        "name": None,
        "zip": None,
        "email": None,
    },
    "task_goal": {
        "intent": None,
        "order_ids": [],
        "description": "",
    },
    "orders": {},
    "items_to_modify": [],
    "missing_info": [],
    "tool_results": [],
    "constraints": [],
    "completed_actions": [],
    "unanswered_questions": [],
    "task_complete": False,
}

# ─── Prompts ──────────────────────────────────────────────────────────────────

_STATE_TRACKER_SYSTEM = """\
You maintain the structured working state for a customer service conversation.
Your only job is to update the state based on the latest message.

Rules:
- Output the COMPLETE updated state as a single JSON object.
- Only update fields where the message provides new explicit information.
- Do NOT invent or infer anything not stated in the message.
- Do NOT make decisions about what to do next.

Update logic:
- User provides name/zip/email → update user_identity fields.
- Tool result contains user_id → set user_identity.user_id and authenticated=true.
- Tool result contains order list → add each order_id to task_goal.order_ids.
- Tool result contains order details → populate orders dict (order_id as key, include status, payment_method_id, items).
- Tool result contains product details → update matching items_to_modify entries (fill replacement_product_id / status=ready).
- Tool result shows a write action succeeded → append {tool, key_args, turn} to completed_actions.
- Tool result says "Transfer successful" → set task_complete=true immediately.
- Tool result is an error → append to tool_results with status="error"; do NOT update other state fields.
- User asks a question (e.g., "how many options?", "what is the price?") → add it to unanswered_questions if not yet answered.
- Agent answers a question → remove it from unanswered_questions.
- Remove resolved items from missing_info.
- Append a one-line summary to tool_results for each message.

Order ID format: ALWAYS store with "#" prefix (e.g., "#W2378156"). If user says "W2378156", store as "#W2378156".

Output only valid JSON. No explanation outside the JSON.\
""".strip()

_REASONER_SYSTEM = """\
You are the decision-making component of a customer service agent.
Based on the current conversation state and the retail policy, decide the agent's next action.
Output ONLY a JSON object. No explanation outside the JSON.

Output format:
{
  "type": "ask_user | call_tool | write_tool | final_reply",
  "reason": "brief reason",
  "ask_content": "what to ask (only when type=ask_user)",
  "tool": "exact tool name (only when type=call_tool or write_tool)",
  "tool_args": { "param": value },
  "reply_content": "key points to cover in final message (include answers to unanswered_questions)",
  "requires_verification": true or false
}

Decision rules (apply in order):
1. User not authenticated → ask_user for name+zip or email.
2. task_goal.intent is unclear → ask_user to clarify.
3. Authenticated, orders empty AND order_ids empty → call_tool get_user_details(user_id=...).
4. Authenticated, orders empty, order_ids has IDs → call_tool get_order_details for first unknown order_id.
5. orders has data but items_to_modify need product lookup → call_tool get_product_details.
6. All items_to_modify ready, write op not in completed_actions → write_tool.
7. task_complete=true OR all goals covered by completed_actions → final_reply.
8. verifier_feedback present → address blocking_issues before re-proposing.
9. turn_count > {MAX_TURNS} → force final_reply with best available summary.

HARD rules:
- requires_verification=true for write_tool and final_reply; false for ask_user and call_tool.
- Include ALL items in ONE write_tool call. Never split writes.
- Order IDs must use "#" prefix in tool_args.
- If a tool call already appears in tool_results with status="error" → do NOT retry same call+args.
- transfer_to_human_agents: ONLY if user explicitly asks for a human, or truly cannot be handled by policy+tools. Never call more than once.
- Never ask for info that can be looked up with a tool.
- For final_reply: reply_content MUST include answers to all items in unanswered_questions.
- get_product_details only accepts product_id as its parameter — do NOT pass options, color, size, or any other kwargs.
- For return/exchange: use the payment_method_id from state.orders[order_id].payment_method_id (the original). Do NOT invent or change it.
- transfer_to_human_agents is ONLY valid when the user explicitly asks for a human, or when the task is truly impossible by policy. Never call it because a tool lookup failed or hit a limit.\
""".strip().replace("{MAX_TURNS}", str(MAX_TURNS))

_VERIFIER_SYSTEM = """\
You verify a proposed action before it is executed.
Output ONLY a JSON object. No explanation outside the JSON.

Output format:
{
  "approved": true or false,
  "blocking_issues": ["issue 1", "issue 2"],
  "required_fix": "what must be corrected, or null if approved"
}

For write_tool — check ALL of:
1. Completeness: all items the user requested are included (no missing items).
2. No duplicate: the same tool+order_id combination does NOT already appear in completed_actions.
3. Order status: matches tool requirement (delivered for exchange/return; pending for cancel/modify/modify_address/modify_payment).
4. Authentication: user_identity.authenticated=true.
5. Argument correctness: item_ids are actual item IDs from the order, not product IDs.
6. Payment method presence: payment_method_id must be present (not null/empty) when required.
7. Cross-payment policy: if the user explicitly requested to refund to a DIFFERENT payment method than the original, that violates policy — reject.
8. Policy compliance: action must comply with the stated policy.
9. transfer_to_human_agents: only if user explicitly requested a human OR truly cannot be handled.

For final_reply — check ALL of:
1. All goals in task_goal are covered by completed_actions.
2. No items_to_modify still pending.

If any check fails → approved=false, list ALL blocking issues with specifics.
If all pass → approved=true, blocking_issues=[].\
""".strip()

_ACTION_GENERATOR_SYSTEM = """\
You are the response generator for a retail customer service agent.
Convert the approved plan into a concise, natural customer-facing message.
Be brief and helpful. Follow the policy tone.
Do not reveal internal state details or reasoning.
For final replies: make sure to answer ALL questions the user asked during the conversation.
Output plain text only — no JSON, no markdown.\
""".strip()


# ─── LangGraph per-turn state ─────────────────────────────────────────────────

class TurnState(TypedDict, total=False):
    structured_state: dict
    latest_message_text: str
    tool_descriptions: str
    policy: str
    turn_count: int

    updated_structured_state: dict
    proposal: dict
    verifier_feedback: dict
    retry_count: int

    read_hint: str       # injected when a read tool hits cap
    action_type: str
    action_content: str
    action_tool_name: str
    action_tool_args: dict


# ─── Persistent agent state ───────────────────────────────────────────────────

class WorkflowTau2AgentState:
    def __init__(
        self,
        messages: list[Any],
        structured_state: dict,
        turn_count: int = 0,
        write_tool_counts: Optional[dict[str, int]] = None,
        read_tool_counts: Optional[dict[str, int]] = None,
    ) -> None:
        self.messages = messages
        self.structured_state = structured_state
        self.turn_count = turn_count
        self.write_tool_counts: dict[str, int] = write_tool_counts or {}
        self.read_tool_counts: dict[str, int] = read_tool_counts or {}


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
        parts = []
        for item in content:
            if isinstance(item, dict):
                parts.append(str(item.get("text", "")))
            else:
                parts.append(str(item))
        return "\n".join(p for p in parts if p)
    return str(content)


# ─── WorkflowTau2Agent ────────────────────────────────────────────────────────

class WorkflowTau2Agent(HalfDuplexAgent[WorkflowTau2AgentState]):
    """4-node workflow: State Tracker → Reasoner → Verifier → Action Generator."""

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
        self._known_tool_names = {
            s.get("function", s).get("name", "") for s in self._raw_schemas
        }
        self._tool_descriptions = self._build_tool_descriptions()
        self._graph = self._build_graph()

    # ── Model ────────────────────────────────────────────────────────────────

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
            param_parts = []
            for pname, pschema in props.items():
                ptype = pschema.get("type", "any")
                marker = "*" if pname in required else ""
                param_parts.append(f"{pname}{marker}:{ptype}")
            lines.append(f"- {name}({', '.join(param_parts)}): {desc}")
        return "\n".join(lines)

    # ── tau2 interface ────────────────────────────────────────────────────────

    def get_init_state(
        self, message_history: Optional[list[Any]] = None
    ) -> WorkflowTau2AgentState:
        from tau2.agent.base_agent import is_valid_agent_history_message
        if message_history is None:
            message_history = []
        assert all(is_valid_agent_history_message(m) for m in message_history)
        return WorkflowTau2AgentState(
            messages=list(message_history),
            structured_state=copy.deepcopy(EMPTY_STRUCTURED_STATE),
        )

    def generate_next_message(
        self, message: Any, state: WorkflowTau2AgentState
    ) -> tuple[Any, WorkflowTau2AgentState]:
        from tau2.data_model.message import AssistantMessage, MultiToolMessage, ToolCall, ToolMessage

        if isinstance(message, MultiToolMessage):
            state.messages.extend(message.tool_messages)
        else:
            state.messages.append(message)

        state.turn_count += 1
        started = time.perf_counter()

        # ── Fix 2: Python-level completed_actions update ──────────────────
        # When we receive a successful write tool result, record it directly
        # without relying on State Tracker LLM to do so reliably.
        tool_messages = (
            message.tool_messages if isinstance(message, MultiToolMessage) else [message]
        )
        for tool_msg in tool_messages:
            if not isinstance(tool_msg, ToolMessage):
                continue
            result_text = tool_msg.content or ""
            if "Error" in result_text or "error" in result_text[:30]:
                continue
            # Find the write tool call that produced this result
            prev_write = self._find_preceding_write_call(state.messages, tool_msg.id)
            if prev_write:
                tool_name, tool_args = prev_write
                existing = state.structured_state.get("completed_actions", [])
                entry = {"tool": tool_name, "turn": state.turn_count}
                if entry not in existing:
                    state.structured_state.setdefault("completed_actions", []).append(entry)
                if tool_name == "transfer_to_human_agents":
                    state.structured_state["task_complete"] = True

        # ── P0: hard write-tool loop guard (bypass LangGraph entirely) ──────
        write_overloaded = [t for t, c in state.write_tool_counts.items() if c >= MAX_WRITE_CALLS]
        if write_overloaded:
            generation_seconds = time.perf_counter() - started
            content = (
                "I've completed the available modifications for this request. "
                "Is there anything else I can help you with?"
            )
            msg = AssistantMessage(
                role="assistant", content=content, tool_calls=None,
                cost=0.0, usage=None,
                raw_data={"workflow": True, "loop_guard": write_overloaded},
                generation_time_seconds=generation_seconds,
            )
            state.messages.append(msg)
            return msg, state

        # ── Read-tool loop guard: inject hint into Reasoner, don't bypass ─
        read_overloaded = [t for t, c in state.read_tool_counts.items() if c >= MAX_READ_CALLS]

        # Build read-loop hint to inject into Reasoner if needed
        read_hint = ""
        if read_overloaded:
            read_hint = (
                "\n\nDO NOT CALL these tools again (lookup limit reached): "
                + ", ".join(read_overloaded)
                + ". You have all available information in the state."
                "\nDo NOT call transfer_to_human_agents because of a lookup limit."
                "\nIf product variant is still unresolved, ask the user to confirm from the options you already have."
            )

        turn_input: TurnState = {
            "structured_state": copy.deepcopy(state.structured_state),
            "updated_structured_state": copy.deepcopy(state.structured_state),
            "latest_message_text": self._serialize_incoming(message),
            "tool_descriptions": self._tool_descriptions,
            "policy": self.domain_policy,
            "turn_count": state.turn_count,
            "retry_count": 0,
            "read_hint": read_hint,
        }

        result: TurnState = self._graph.invoke(turn_input, config={"recursion_limit": 20})
        generation_seconds = time.perf_counter() - started

        if result.get("updated_structured_state"):
            state.structured_state = result["updated_structured_state"]

        action_type = result.get("action_type", "text")
        if action_type == "tool_call":
            tool_name = result.get("action_tool_name", "")
            tool_args = result.get("action_tool_args", {})
            call_id = f"wf_{state.turn_count}_0"

            if tool_name in WRITE_TOOLS:
                state.write_tool_counts[tool_name] = (
                    state.write_tool_counts.get(tool_name, 0) + 1
                )
            else:
                state.read_tool_counts[tool_name] = (
                    state.read_tool_counts.get(tool_name, 0) + 1
                )

            assistant_message = AssistantMessage(
                role="assistant", content=None,
                tool_calls=[ToolCall(id=call_id, name=tool_name, arguments=tool_args)],
                cost=0.0, usage=None,
                raw_data={"workflow": True, "proposal": result.get("proposal", {})},
                generation_time_seconds=generation_seconds,
            )
        else:
            content = result.get("action_content") or "How can I help you?"
            assistant_message = AssistantMessage(
                role="assistant", content=content, tool_calls=None,
                cost=0.0, usage=None,
                raw_data={"workflow": True, "proposal": result.get("proposal", {})},
                generation_time_seconds=generation_seconds,
            )

        state.messages.append(assistant_message)
        return assistant_message, state

    def _find_preceding_write_call(
        self, messages: list[Any], tool_call_id: str
    ) -> tuple[str, dict] | None:
        """Find the write tool call that produced the given tool_call_id result."""
        from tau2.data_model.message import AssistantMessage as Tau2AssistantMessage
        for msg in reversed(messages):
            if not isinstance(msg, Tau2AssistantMessage):
                continue
            for tc in (msg.tool_calls or []):
                if tc.id == tool_call_id and tc.name in WRITE_TOOLS:
                    return tc.name, tc.arguments
        return None

    def stop(self, message: Any = None, state: Any = None) -> None:
        return None

    def set_seed(self, seed: int) -> None:
        self.llm_args["seed"] = seed
        self._model = self._build_model()

    # ── Serialization ─────────────────────────────────────────────────────────

    def _serialize_incoming(self, message: Any) -> str:
        from tau2.data_model.message import MultiToolMessage
        if isinstance(message, MultiToolMessage):
            return "\n".join(self._serialize_one(m) for m in message.tool_messages)
        return self._serialize_one(message)

    def _serialize_one(self, message: Any) -> str:
        from tau2.data_model.message import ToolMessage, UserMessage
        if isinstance(message, UserMessage):
            return f"[User message]\n{message.content or ''}"
        if isinstance(message, ToolMessage):
            return f"[Tool result id={message.id}]\n{message.content or ''}"
        return f"[Message]\n{message}"

    # ── LangGraph graph ───────────────────────────────────────────────────────

    def _build_graph(self):
        known_tools = self._known_tool_names

        # ── State Tracker ─────────────────────────────────────────────────
        def state_tracker_node(state: TurnState) -> dict:
            prompt = (
                f"Current state:\n{json.dumps(state['structured_state'], indent=2)}\n\n"
                f"Latest message:\n{state['latest_message_text']}"
            )
            response = self._model.invoke([
                SystemMessage(content=_STATE_TRACKER_SYSTEM),
                HumanMessage(content=prompt),
            ])
            parsed = _parse_json(_content_to_text(response.content))
            if parsed and isinstance(parsed, dict):
                # Ensure unanswered_questions key exists
                if "unanswered_questions" not in parsed:
                    parsed["unanswered_questions"] = (
                        state["structured_state"].get("unanswered_questions", [])
                    )
                return {"updated_structured_state": parsed}
            return {"updated_structured_state": copy.deepcopy(state["structured_state"])}

        # ── Reasoner ──────────────────────────────────────────────────────
        def reasoner_node(state: TurnState) -> dict:
            structured = state.get("updated_structured_state", state["structured_state"])
            feedback = state.get("verifier_feedback")

            feedback_section = ""
            if feedback and not feedback.get("approved", True):
                issues = "\n".join(f"- {i}" for i in feedback.get("blocking_issues", []))
                prev = json.dumps(state.get("proposal", {}), indent=2)
                feedback_section = (
                    f"\n\nVerifier rejected the previous proposal.\nBlocking issues:\n{issues}"
                    f"\nRequired fix: {feedback.get('required_fix', '')}"
                    f"\nPrevious proposal:\n{prev}"
                )

            prompt = (
                f"turn_count: {state.get('turn_count', 0)}\n\n"
                f"Current state:\n{json.dumps(structured, indent=2)}\n\n"
                f"Available tools:\n{state['tool_descriptions']}\n\n"
                f"Policy:\n{state['policy']}"
                + feedback_section
                + (state.get("read_hint") or "")
            )
            response = self._model.invoke([
                SystemMessage(content=_REASONER_SYSTEM),
                HumanMessage(content=prompt),
            ])
            parsed = _parse_json(_content_to_text(response.content))
            if not parsed or "type" not in parsed:
                parsed = {
                    "type": "ask_user",
                    "reason": "Could not determine next action",
                    "ask_content": "Could you please clarify what you need?",
                    "requires_verification": False,
                }
            return {"proposal": parsed}

        # ── Verifier ──────────────────────────────────────────────────────
        def verifier_node(state: TurnState) -> dict:
            structured = state.get("updated_structured_state", state["structured_state"])
            proposal = state.get("proposal", {})
            prompt = (
                f"Current state:\n{json.dumps(structured, indent=2)}\n\n"
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

        # Build valid-params map for P1+B fixes
        valid_params: dict[str, set[str]] = {}
        for schema in self._raw_schemas:
            fn = schema.get("function", schema)
            name = fn.get("name", "")
            props = fn.get("parameters", {}).get("properties", {})
            valid_params[name] = set(props.keys())

        # ── Action Generator ──────────────────────────────────────────────
        def action_generator_node(state: TurnState) -> dict:
            proposal = state.get("proposal", {})
            action_type = proposal.get("type", "ask_user")

            # Tool calls: deterministic — validate name (P1) and strip invalid args (fix B)
            if action_type in ("call_tool", "write_tool"):
                tool_name = proposal.get("tool", "")
                if tool_name not in known_tools:
                    return {
                        "action_type": "text",
                        "action_content": (
                            "I need a moment to look into this further. "
                            "Could you give me a moment?"
                        ),
                    }
                # Strip any args not in the tool's declared parameters
                raw_args = proposal.get("tool_args", {})
                allowed = valid_params.get(tool_name, set())
                clean_args = {k: v for k, v in raw_args.items() if k in allowed}
                return {
                    "action_type": "tool_call",
                    "action_tool_name": tool_name,
                    "action_tool_args": clean_args,
                }

            # Text generation for ask_user and final_reply
            structured = state.get("updated_structured_state", state["structured_state"])
            unanswered = structured.get("unanswered_questions", [])

            if action_type == "ask_user":
                intent = proposal.get("ask_content", "clarify the request")
                user_prompt = f"Ask the user for the following: {intent}\nGenerate a brief, natural question."
            else:
                intent = proposal.get("reply_content", "confirm the completed action")
                extra = ""
                if unanswered:
                    extra = f"\n\nAlso answer these questions the user asked: {unanswered}"
                user_prompt = (
                    f"Generate a final confirmation message covering: {intent}{extra}\n"
                    f"Make sure to address everything the user asked about."
                )

            response = self._model.invoke([
                SystemMessage(content=_ACTION_GENERATOR_SYSTEM + f"\n\nPolicy:\n{state['policy']}"),
                HumanMessage(content=user_prompt),
            ])
            text = _content_to_text(response.content)
            return {
                "action_type": "text",
                "action_content": text or "How can I help you?",
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
        def route_after_reasoner(
            state: TurnState,
        ) -> Literal["verifier", "action_generator"]:
            if state.get("proposal", {}).get("requires_verification", False):
                return "verifier"
            return "action_generator"

        def route_after_verifier(
            state: TurnState,
        ) -> Literal["action_generator", "bump_retry", "safe_fallback"]:
            feedback = state.get("verifier_feedback", {})
            if feedback.get("approved", True):
                return "action_generator"
            if state.get("retry_count", 0) < MAX_VERIFIER_RETRIES:
                return "bump_retry"
            return "safe_fallback"

        # ── Build graph ───────────────────────────────────────────────────
        graph = StateGraph(TurnState)
        graph.add_node("state_tracker", state_tracker_node)
        graph.add_node("reasoner", reasoner_node)
        graph.add_node("verifier", verifier_node)
        graph.add_node("action_generator", action_generator_node)
        graph.add_node("bump_retry", bump_retry_node)
        graph.add_node("safe_fallback", safe_fallback_node)

        graph.add_edge(START, "state_tracker")
        graph.add_edge("state_tracker", "reasoner")
        graph.add_conditional_edges(
            "reasoner",
            route_after_reasoner,
            {"verifier": "verifier", "action_generator": "action_generator"},
        )
        graph.add_conditional_edges(
            "verifier",
            route_after_verifier,
            {
                "action_generator": "action_generator",
                "bump_retry": "bump_retry",
                "safe_fallback": "safe_fallback",
            },
        )
        graph.add_edge("bump_retry", "reasoner")
        graph.add_edge("action_generator", END)
        graph.add_edge("safe_fallback", END)

        return graph.compile()


# ─── Factory + registration ───────────────────────────────────────────────────

def create_workflow_tau2_agent(
    tools: list[Any],
    domain_policy: str,
    llm: str,
    llm_args: Optional[dict[str, Any]] = None,
    **_: Any,
) -> WorkflowTau2Agent:
    return WorkflowTau2Agent(
        tools=tools, domain_policy=domain_policy, llm=llm, llm_args=llm_args,
    )


def register_workflow_tau2_agent() -> None:
    from tau2.registry import registry
    if registry.get_agent_factory(TAU2_WORKFLOW_AGENT_NAME) is None:
        registry.register_agent_factory(
            create_workflow_tau2_agent,
            TAU2_WORKFLOW_AGENT_NAME,
        )
