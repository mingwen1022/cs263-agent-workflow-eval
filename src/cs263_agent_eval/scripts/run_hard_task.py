"""Run hard tasks on agent baselines and/or the agentic workflow."""

from __future__ import annotations

import json
import argparse
from statistics import mean

from cs263_agent_eval.agents.runner import run_single_agent, run_agentic_workflow
from cs263_agent_eval.benchmark.hard_tasks import list_hard_task_ids, load_hard_task
from cs263_agent_eval.eval.scoring import score_prediction
from cs263_agent_eval.model_factory import get_small_ollama_llm, get_vertex_llm

_ALL_SYSTEMS = ["large_single", "small_single", "small_workflow"]


def _record_to_printable(record):
    failed_checks = []
    if record.scores:
        failed_checks = [
            check["check_id"]
            for check in record.scores.details.get("checks", [])
            if not check["correct"]
        ]
    return {
        "task_id": record.task_id,
        "system_name": record.system_name,
        "answer": record.prediction.answer,
        "score_percent": record.scores.score_percent if record.scores else None,
        "correct_checks": record.scores.details.get("correct_checks") if record.scores else None,
        "total_checks": record.scores.details.get("total_checks") if record.scores else None,
        "failed_checks": failed_checks,
        "latency_sec": record.latency_sec,
        "tool_calls": [
            {"tool_name": item.get("tool_name"), "args": item.get("args")}
            for item in record.prediction.tool_log
        ],
        "error": record.error,
        "notes": record.prediction.notes[:500] if record.prediction.notes else "",
    }


def _run_system(system_name: str, task, small_llm, large_llm):
    if system_name == "large_single":
        return run_single_agent(task, large_llm, "large_single")
    elif system_name == "small_single":
        return run_single_agent(task, small_llm, "small_single")
    elif system_name == "small_workflow":
        return run_agentic_workflow(task, small_llm, "small_agentic_workflow")
    else:
        raise ValueError(f"Unknown system: {system_name}")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--task-id",
        choices=list_hard_task_ids(),
        default=None,
        help="Run one task. By default, run all hard tasks.",
    )
    parser.add_argument(
        "--system",
        choices=_ALL_SYSTEMS,
        nargs="+",
        default=["large_single", "small_single"],
        help="Which systems to run. Default: large_single small_single.",
    )
    args = parser.parse_args()

    task_ids = [args.task_id] if args.task_id else list_hard_task_ids()
    systems = args.system

    small_llm = get_small_ollama_llm() if any(
        s in systems for s in ("small_single", "small_workflow")
    ) else None
    large_llm = get_vertex_llm() if "large_single" in systems else None

    printable_records = []
    for task_id in task_ids:
        task = load_hard_task(task_id)
        for system_name in systems:
            record = _run_system(system_name, task, small_llm, large_llm)
            if not record.error:
                record.scores = score_prediction(task, record.prediction.answer)
            printable_records.append(_record_to_printable(record))

    summaries = {}
    for system_name in systems:
        # small_workflow is stored as small_agentic_workflow in RunRecord
        key = "small_agentic_workflow" if system_name == "small_workflow" else system_name
        scores = [
            item["score_percent"]
            for item in printable_records
            if item["system_name"] == key and item["score_percent"] is not None
        ]
        summaries[system_name] = {
            "avg_score_percent": round(mean(scores), 2) if scores else None,
            "num_scored_tasks": len(scores),
        }

    print(json.dumps({"summary": summaries, "runs": printable_records}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
