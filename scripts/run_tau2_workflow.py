"""Run the tau2 retail benchmark with the workflow agent."""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

from dotenv import load_dotenv


ROOT = Path(__file__).resolve().parents[1]
PROJECT_SRC = ROOT / "src"
TAU2_SRC = ROOT / "third_party" / "tau2-bench" / "src"
DEFAULT_CONFIG = ROOT / "configs" / "tau2" / "retail_50.json"
DEFAULT_RESULTS_DIR = ROOT / "results" / "tau2_retail"


def prepare_env() -> None:
    load_dotenv(dotenv_path=ROOT / ".env")
    os.environ.setdefault("TAU2_DATA_DIR", str(ROOT / "data"))
    os.environ.setdefault("VERTEXAI_PROJECT", os.getenv("PROJECT_ID", ""))
    os.environ.setdefault("VERTEXAI_LOCATION", "global")
    if str(PROJECT_SRC) not in sys.path:
        sys.path.insert(0, str(PROJECT_SRC))
    if str(TAU2_SRC) not in sys.path:
        sys.path.insert(0, str(TAU2_SRC))


def load_config(path: Path) -> dict[str, Any]:
    with open(path) as fp:
        return json.load(fp)


def build_task_ids(config: dict[str, Any], num_tasks: int | None) -> list[str]:
    task_ids = [str(t) for t in config["task_ids"]]
    return task_ids if num_tasks is None else task_ids[:num_tasks]


def simulation_summary(simulation: Any) -> dict[str, Any]:
    reward = None
    ri = getattr(simulation, "reward_info", None)
    if ri is not None:
        reward = ri.reward
    return {
        "task_id": simulation.task_id,
        "trial": simulation.trial,
        "reward": reward,
        "success": reward == 1.0,
        "termination_reason": str(simulation.termination_reason),
        "duration": simulation.duration,
        "agent_cost": simulation.agent_cost,
        "user_cost": simulation.user_cost,
    }


def write_summary(results: Any, output_dir: Path, metrics: Any, task_ids: list[str]) -> None:
    task_order = {tid: i for i, tid in enumerate(task_ids)}
    simulations = sorted(
        (simulation_summary(s) for s in results.simulations),
        key=lambda x: (task_order.get(x["task_id"], len(task_order)), x["trial"]),
    )
    summary = {
        "created_at": datetime.now().isoformat(timespec="seconds"),
        "task_ids": task_ids,
        "metrics": metrics.as_dict(),
        "simulations": simulations,
    }
    with open(output_dir / "summary.json", "w") as fp:
        json.dump(summary, fp, indent=2)


def configure_tau2_nl_assertion_judge(config: dict[str, Any]) -> None:
    judge_config = config.get("nl_assertion_judge") or config["user_simulator"]
    judge_model = judge_config["llm"]
    judge_args = judge_config.get("llm_args", {})

    import tau2.config as tau2_config
    import tau2.evaluator.evaluator_nl_assertions as nl_assertions

    tau2_config.DEFAULT_LLM_NL_ASSERTIONS = judge_model
    tau2_config.DEFAULT_LLM_NL_ASSERTIONS_ARGS = judge_args
    nl_assertions.DEFAULT_LLM_NL_ASSERTIONS = judge_model
    nl_assertions.DEFAULT_LLM_NL_ASSERTIONS_ARGS = judge_args


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    parser.add_argument("--agent-key", default="workflow_large",
                        help="Key in agent_systems config (default: workflow_large)")
    parser.add_argument("--num-tasks", type=int, default=20)
    parser.add_argument("--max-concurrency", type=int, default=None)
    parser.add_argument("--save-name", default=None)
    parser.add_argument("--log-level", default="INFO")
    parser.add_argument("--console-display", action="store_true")
    parser.add_argument("--auto-resume", action="store_true")
    args = parser.parse_args()

    prepare_env()

    from tau2.data_model.simulation import TextRunConfig
    from tau2.evaluator.evaluator import EvaluationType
    from tau2.metrics.agent_metrics import compute_metrics
    from tau2.runner.batch import run_tasks
    from tau2.runner.helpers import get_tasks

    from cs263_agent_eval.tau2.workflow_agent import register_workflow_tau2_agent

    register_workflow_tau2_agent()

    config = load_config(args.config)
    configure_tau2_nl_assertion_judge(config)
    agent_config = config["agent_systems"][args.agent_key]
    user_config = config["user_simulator"]
    task_ids = build_task_ids(config, args.num_tasks)

    run_name = args.save_name
    if run_name is None:
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        run_name = f"{timestamp}_{args.agent_key}_{config['domain']}_{len(task_ids)}"

    output_dir = DEFAULT_RESULTS_DIR / run_name
    output_dir.mkdir(parents=True, exist_ok=True)
    save_path = output_dir / "results.json"

    tasks = get_tasks(
        task_set_name=config.get("task_set_name") or config["domain"],
        task_split_name=config.get("task_split_name"),
        task_ids=task_ids,
    )

    run_config = TextRunConfig(
        domain=config["domain"],
        task_set_name=config.get("task_set_name"),
        task_split_name=config.get("task_split_name"),
        task_ids=task_ids,
        agent=agent_config["implementation"],
        llm_agent=agent_config["llm"],
        llm_args_agent=agent_config.get("llm_args", {}),
        user=user_config["implementation"],
        llm_user=user_config["llm"],
        llm_args_user=user_config.get("llm_args", {}),
        num_trials=config.get("num_trials", 1),
        max_steps=config.get("max_steps", 200),
        max_errors=config.get("max_errors", 10),
        max_concurrency=args.max_concurrency or config.get("max_concurrency", 1),
        seed=config.get("seed", 300),
        log_level=args.log_level,
        auto_resume=args.auto_resume,
        hallucination_retries=0,
    )

    print(f"Running {len(tasks)} tau2 retail task(s)")
    print(f"Task ids: {', '.join(task_ids)}")
    print(f"Agent: {run_config.agent} / {run_config.llm_agent}")
    print(f"User simulator: {run_config.user} / {run_config.llm_user}")
    print(f"Saving to: {save_path}")

    results = run_tasks(
        run_config,
        tasks,
        save_path=save_path,
        save_dir=output_dir,
        evaluation_type=EvaluationType.ALL,
        console_display=args.console_display,
        results_format="json",
    )
    results.save(save_path, format="json")

    metrics = compute_metrics(results)
    write_summary(results, output_dir, metrics, task_ids)

    print("Completed")
    print(json.dumps(metrics.as_dict(), indent=2))
    print(f"Summary: {output_dir / 'summary.json'}")


if __name__ == "__main__":
    main()
