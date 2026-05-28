"""Runtime helpers for single-agent baselines."""

from __future__ import annotations

import json
import re
import time
from typing import Any

from langchain_core.messages import AIMessage, ToolMessage

from cs263_agent_eval.agents.single_agent import build_baseline_prompt, build_single_agent
from cs263_agent_eval.config import settings
from cs263_agent_eval.schemas import AgentPrediction, BenchmarkTask, RunRecord, SystemName
from cs263_agent_eval.tools.local_tools import make_source_tools


def _text_from_content(content: Any) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = []
        for item in content:
            if isinstance(item, dict):
                parts.append(str(item.get("text", "")))
            else:
                parts.append(str(item))
        return "\n".join(parts)
    return str(content)


def parse_json_object(content: Any) -> dict[str, Any]:
    text = _text_from_content(content).strip()
    try:
        parsed = json.loads(text)
        return parsed if isinstance(parsed, dict) else {}
    except json.JSONDecodeError:
        pass

    fenced = re.search(r"```(?:json)?\s*(.*?)\s*```", text, re.DOTALL)
    if fenced:
        try:
            parsed = json.loads(fenced.group(1))
            return parsed if isinstance(parsed, dict) else {}
        except json.JSONDecodeError:
            pass

    bracketed = re.search(r"\{.*\}", text, re.DOTALL)
    if bracketed:
        try:
            parsed = json.loads(bracketed.group(0))
            return parsed if isinstance(parsed, dict) else {}
        except json.JSONDecodeError:
            pass
    return {}


def extract_tool_log(messages: list[Any]) -> list[dict[str, Any]]:
    tool_log: list[dict[str, Any]] = []
    tool_call_index: dict[str, int] = {}

    for message in messages:
        if isinstance(message, AIMessage) and getattr(message, "tool_calls", None):
            for tool_call in message.tool_calls:
                index = len(tool_log)
                tool_log.append(
                    {
                        "tool_name": tool_call.get("name"),
                        "args": tool_call.get("args", {}),
                    }
                )
                if tool_call.get("id"):
                    tool_call_index[tool_call["id"]] = index
        elif isinstance(message, ToolMessage):
            call_id = getattr(message, "tool_call_id", None)
            if call_id in tool_call_index:
                tool_log[tool_call_index[call_id]]["result"] = message.content

    return tool_log


def _last_ai_text(messages: list[Any]) -> str:
    for message in reversed(messages):
        if isinstance(message, AIMessage) and not getattr(message, "tool_calls", None):
            return _text_from_content(message.content)
    return ""


def run_agentic_workflow(task: BenchmarkTask, llm: Any, system_name: SystemName) -> RunRecord:
    """Run the planner→collector→reasoner→verifier workflow with the small model."""
    from cs263_agent_eval.workflows.small_agentic_workflow import build_small_agentic_workflow

    tools = make_source_tools(task.sources)
    workflow = build_small_agentic_workflow(llm, tools)

    initial_state = {
        "task_instruction": task.instruction,
        "task_sources": task.sources,
        "revision_count": 0,
        "tool_log": [],
    }

    started = time.time()
    try:
        result = workflow.invoke(initial_state)
        latency = time.time() - started
        answer = result.get("final_answer") or {}
        # fall back to draft if verifier never approved
        if not answer:
            draft = result.get("draft_answer") or {}
            answer = {k: v for k, v in draft.items() if k != "_evidence"}
        tool_log = result.get("tool_log") or []
        prediction = AgentPrediction(answer=answer, tool_log=tool_log)
        return RunRecord(
            task_id=task.task_id,
            system_name=system_name,
            prediction=prediction,
            latency_sec=round(latency, 2),
        )
    except Exception as exc:
        return RunRecord(
            task_id=task.task_id,
            system_name=system_name,
            prediction=AgentPrediction(),
            latency_sec=round(time.time() - started, 2),
            error=str(exc),
        )


def run_single_agent(task: BenchmarkTask, llm: Any, system_name: SystemName) -> RunRecord:
    tools = make_source_tools(task.sources)
    agent = build_single_agent(
        model=llm,
        tools=tools,
        system_prompt=build_baseline_prompt(task.evaluation_criteria.exact_fields),
    )

    started = time.time()
    try:
        result = agent.invoke(
            {"messages": [{"role": "user", "content": task.instruction}]},
            config={"recursion_limit": settings.max_agent_steps * 3},
        )
        latency = time.time() - started
        messages = result.get("messages", [])
        answer = parse_json_object(result.get("structured_response") or _last_ai_text(messages))
        prediction = AgentPrediction(
            answer=answer,
            tool_log=extract_tool_log(messages),
            notes=_last_ai_text(messages) if not answer else "",
        )
        return RunRecord(
            task_id=task.task_id,
            system_name=system_name,
            prediction=prediction,
            latency_sec=round(latency, 2),
        )
    except Exception as exc:
        return RunRecord(
            task_id=task.task_id,
            system_name=system_name,
            prediction=AgentPrediction(),
            latency_sec=round(time.time() - started, 2),
            error=str(exc),
        )
