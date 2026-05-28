"""Small-model planner / collector / reasoner / verifier workflow."""

from __future__ import annotations

import json
import re
from typing import Any, Literal, TypedDict

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage
from langgraph.graph import END, START, StateGraph

from cs263_agent_eval.agents.single_agent import build_single_agent
from cs263_agent_eval.agents.runner import parse_json_object, _text_from_content
from cs263_agent_eval.config import settings


# ─────────────────────────────────── Prompts ─────────────────────────────

_PLANNER_SYSTEM = """\
You are a task planner. Read the task instruction and produce a JSON plan.

Output only a JSON object with these keys:
  "fields_to_produce": list of output field names required by the task
  "sub_questions": list of {"field": ..., "question": ...} — one per field
  "exclusion_reminders": list of things the instruction says to exclude/ignore

No explanation outside the JSON."""


_COLLECTOR_SYSTEM = """\
You are a document reader. Your only job is to read every available source and \
extract the most important facts.

Steps:
1. Call list_sources to get the full list of source IDs.
2. Read EVERY source using the matching tool (read_csv / read_pdf / read_docx / \
read_text_source / read_source). Do NOT skip any source.
3. After reading ALL sources, write a structured summary in this format:

=== KEY NUMBERS AND DATA ===
(all numeric values, dates, quantities, rates, thresholds found across sources;
 if a source contains both an included/limit quantity and an actual quantity for
 the same metric, state both and whether the actual exceeds the limit)

=== RULES AND POLICIES ===
(all eligibility criteria, calculation rules, exclusion rules, caps, approval \
requirements)

=== ITEMS AND THEIR ATTRIBUTES ===
(for each entity / row / entry relevant to the task: list its key attributes \
side by side so comparisons are easy)

=== OUT-OF-SCOPE / NOISE ===
(items clearly not relevant: wrong ID, wrong period, different entity, voided, etc.)

Do NOT answer the task — only extract and organize what the sources say."""


_REASONER_SYSTEM = """\
You are a precise analyst. Use the evidence notes provided. If a specific value \
is missing or unclear in the evidence, you may re-read the relevant source using \
the available tools. Follow these rules strictly.

━━ NUMERIC FIELDS ━━
For every numeric field:
1. Identify the BASE value from evidence (e.g., base fee, starting amount).
2. Identify ALL adjustments: overages, corrections, caps, deductions.
   - Overage formula: (actual_quantity - included_quantity) × unit_rate
   - Cap formula: min(computed_value, cap_limit)
   - Correction: replace original with corrected value before summing
3. Call run_calculation for each arithmetic step. Show the expression first.
4. Sum all components: call run_calculation("base + adj1 + adj2 + ...").

━━ SET / ARRAY FIELDS ━━
For every set field:
1. List ALL candidate items from the evidence (do not skip any).
2. For EACH candidate, apply EVERY relevant rule one by one:
   - "Does item X meet criterion A?" → yes/no + source citation
   - "Does item X meet criterion B?" → yes/no + source citation
3. Include the item ONLY if it passes all inclusion criteria.
4. Exclude the item if it fails any exclusion criterion.
5. Use short snake_case labels.

━━ OUTPUT ━━
Return one JSON object with all required fields.
Add an "_evidence" key mapping each field to its source citation.
No explanation outside the JSON."""


_VERIFIER_SYSTEM = """\
You are a strict verifier. Check the draft answer field by field.

For NUMERIC fields:
1. Re-read the evidence for base value AND all overages/corrections.
2. Re-compute from scratch with run_calculation. Does it match the draft?
3. If not, report arithmetic_error with the correct expression.

For SET/ARRAY fields:
1. List every item in the evidence that could belong to this field.
2. Check: is each gold-standard item present in the draft?
3. Check: does every draft item have clear evidence support?
4. Report missing_item or extra_item as appropriate.

Return JSON:
{"verdict": "approved", "issues": []}
OR
{"verdict": "revise", "issues": [
  {"field": "...",
   "type": "arithmetic_error | missing_item | extra_item | unsupported_value",
   "detail": "...",
   "correction_hint": "..."}
]}

Be specific: give the exact correct value or missing item in correction_hint.
No explanation outside the JSON."""


# ─────────────────────────────────── State ───────────────────────────────

class WorkflowState(TypedDict, total=False):
    task_instruction: str
    task_sources: dict[str, Any]     # source_id -> file path (for safety-net reads)
    plan: dict[str, Any]
    evidence: str                    # formatted evidence string from Collector
    draft_answer: dict[str, Any]
    verifier_feedback: dict[str, Any]
    revision_count: int
    final_answer: dict[str, Any]
    tool_log: list[dict[str, Any]]
    error: str | None


# ─────────────────────────────────── Helpers ─────────────────────────────

def _extract_evidence(messages: list[Any]) -> str:
    """Build a formatted evidence string from agent message history."""
    tool_calls: dict[str, dict] = {}
    parts: list[str] = []

    for msg in messages:
        if isinstance(msg, AIMessage) and getattr(msg, "tool_calls", None):
            for tc in msg.tool_calls:
                if tc.get("id"):
                    tool_calls[tc["id"]] = tc
        elif isinstance(msg, ToolMessage):
            tc = tool_calls.get(getattr(msg, "tool_call_id", None), {})
            name = tc.get("name", "")
            args = tc.get("args", {})
            content = msg.content if isinstance(msg.content, str) else str(msg.content)

            if name == "list_sources":
                parts.append(f"=== AVAILABLE SOURCES ===\n{content}")
            elif name in ("read_source", "read_text_source", "read_csv",
                          "read_pdf", "read_docx"):
                sid = args.get("source_id", "unknown")
                parts.append(f"=== SOURCE: {sid} ===\n{content}")

    return "\n\n".join(parts)


def _force_read_missing(
    evidence: str,
    task_sources: dict[str, Any],
    tool_dict: dict[str, Any],
) -> str:
    """Programmatically read any sources the agent missed."""
    read_ids: set[str] = set()
    for line in evidence.splitlines():
        m = re.match(r"=== SOURCE: (\S+)", line)
        if m:
            read_ids.add(m.group(1))

    extra_parts: list[str] = []
    for sid in sorted(set(task_sources.keys()) - read_ids):
        read_tool = tool_dict.get("read_source")
        if read_tool:
            try:
                content = read_tool.invoke({"source_id": sid})
                extra_parts.append(f"=== SOURCE: {sid} (force-read) ===\n{content}")
            except Exception:
                pass

    if extra_parts:
        evidence = evidence + "\n\n" + "\n\n".join(extra_parts)
    return evidence


def _last_ai_text(messages: list[Any]) -> str:
    for msg in reversed(messages):
        if isinstance(msg, AIMessage) and not getattr(msg, "tool_calls", None):
            return _text_from_content(msg.content)
    return ""


def _collect_tool_log(messages: list[Any]) -> list[dict[str, Any]]:
    from cs263_agent_eval.agents.runner import extract_tool_log
    return extract_tool_log(messages)


# ─────────────────────────────────── Workflow factory ────────────────────

def build_small_agentic_workflow(llm: Any, tools: list[Any]):
    """Build the compiled LangGraph workflow. Call once per (task, llm) pair."""

    tool_dict = {t.name: t for t in tools}
    calc_tools = [t for t in tools if t.name == "run_calculation"]
    recursion = settings.max_agent_steps * 3

    # ── Node: Planner ────────────────────────────────────────────────────
    def planner_node(state: WorkflowState) -> WorkflowState:
        response = llm.invoke([
            SystemMessage(content=_PLANNER_SYSTEM),
            HumanMessage(content=state["task_instruction"]),
        ])
        plan = parse_json_object(_text_from_content(response.content)) or {}
        return {"plan": plan}

    # ── Node: Collector ──────────────────────────────────────────────────
    collector_agent = build_single_agent(llm, tools, _COLLECTOR_SYSTEM)

    def collector_node(state: WorkflowState) -> WorkflowState:
        feedback = state.get("verifier_feedback", {})
        issues_str = ""
        if feedback.get("issues"):
            issues_str = (
                "\n\n[ISSUES FROM VERIFIER — re-read sources to resolve these]\n"
                + json.dumps(feedback["issues"], indent=2)
            )

        user_msg = state["task_instruction"] + issues_str

        result = collector_agent.invoke(
            {"messages": [{"role": "user", "content": user_msg}]},
            config={"recursion_limit": recursion},
        )
        messages = result.get("messages", [])
        raw_evidence = _extract_evidence(messages)
        raw_evidence = _force_read_missing(
            raw_evidence, state.get("task_sources", {}), tool_dict
        )
        # Append the agent's own summary text (the last AI message)
        agent_summary = _last_ai_text(messages)
        if agent_summary and len(agent_summary) > 50:
            evidence = raw_evidence + "\n\n=== COLLECTOR SUMMARY ===\n" + agent_summary
        else:
            evidence = raw_evidence

        new_log = (state.get("tool_log") or []) + _collect_tool_log(messages)
        return {"evidence": evidence, "tool_log": new_log}

    # ── Node: Reasoner ───────────────────────────────────────────────────
    reasoner_agent = build_single_agent(llm, tools, _REASONER_SYSTEM)

    def reasoner_node(state: WorkflowState) -> WorkflowState:
        plan = state.get("plan", {})
        evidence = state.get("evidence", "")
        feedback = state.get("verifier_feedback", {})

        issues_section = ""
        prev_draft_section = ""
        if feedback.get("issues"):
            issues_section = (
                "\n\n[ISSUES TO FIX]\n"
                + json.dumps(feedback["issues"], indent=2)
            )
            prev_draft = {
                k: v for k, v in (state.get("draft_answer") or {}).items()
                if k != "_evidence"
            }
            prev_draft_section = (
                "\n\n[PREVIOUS DRAFT — fix the issues above]\n"
                + json.dumps(prev_draft, indent=2)
            )

        user_msg = (
            state["task_instruction"]
            + "\n\n[EVIDENCE FROM ALL SOURCES]\n"
            + evidence
            + prev_draft_section
            + issues_section
        )

        result = reasoner_agent.invoke(
            {"messages": [{"role": "user", "content": user_msg}]},
            config={"recursion_limit": recursion},
        )
        messages = result.get("messages", [])
        raw = result.get("structured_response") or _last_ai_text(messages)
        draft = parse_json_object(raw) or {}

        new_log = (state.get("tool_log") or []) + _collect_tool_log(messages)
        return {"draft_answer": draft, "tool_log": new_log}

    # ── Node: Verifier ───────────────────────────────────────────────────
    verifier_agent = build_single_agent(llm, calc_tools, _VERIFIER_SYSTEM)

    def verifier_node(state: WorkflowState) -> WorkflowState:
        evidence = state.get("evidence", "")
        draft = state.get("draft_answer", {})
        draft_clean = {k: v for k, v in draft.items() if k != "_evidence"}

        user_msg = (
            state["task_instruction"]
            + "\n\n[EVIDENCE FROM ALL SOURCES]\n"
            + evidence
            + "\n\n[DRAFT ANSWER TO VERIFY]\n"
            + json.dumps(draft_clean, indent=2)
        )

        result = verifier_agent.invoke(
            {"messages": [{"role": "user", "content": user_msg}]},
            config={"recursion_limit": recursion},
        )
        messages = result.get("messages", [])
        raw = result.get("structured_response") or _last_ai_text(messages)
        feedback = parse_json_object(raw) or {"verdict": "approved", "issues": []}

        # Default to approved if parsing fails to avoid infinite loops
        if "verdict" not in feedback:
            feedback = {"verdict": "approved", "issues": []}

        final = {k: v for k, v in draft_clean.items()}
        new_log = (state.get("tool_log") or []) + _collect_tool_log(messages)

        updates: WorkflowState = {
            "verifier_feedback": feedback,
            "tool_log": new_log,
        }
        if feedback.get("verdict") == "approved":
            updates["final_answer"] = final
        return updates

    # ── Routing ──────────────────────────────────────────────────────────
    def route_after_verifier(
        state: WorkflowState,
    ) -> Literal["collector", "__end__"]:
        feedback = state.get("verifier_feedback", {})
        count = state.get("revision_count", 0)
        if (
            feedback.get("verdict") == "revise"
            and count < settings.max_workflow_revisions
        ):
            return "collector"
        return "__end__"

    def bump_revision(state: WorkflowState) -> WorkflowState:
        """Increment revision counter before re-entering collector."""
        return {"revision_count": state.get("revision_count", 0) + 1}

    # ── Build graph ──────────────────────────────────────────────────────
    graph = StateGraph(WorkflowState)
    graph.add_node("planner", planner_node)
    graph.add_node("collector", collector_node)
    graph.add_node("reasoner", reasoner_node)
    graph.add_node("verifier", verifier_node)
    graph.add_node("bump_revision", bump_revision)

    graph.add_edge(START, "planner")
    graph.add_edge("planner", "collector")
    graph.add_edge("collector", "reasoner")
    graph.add_edge("reasoner", "verifier")
    graph.add_conditional_edges(
        "verifier",
        route_after_verifier,
        {"collector": "bump_revision", "__end__": END},
    )
    graph.add_edge("bump_revision", "collector")

    return graph.compile()
