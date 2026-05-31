"""Smoke-test tau2 retail user simulator with Vertex Gemini.

This verifies only the user simulator side:
- tau2 retail data loads from this repo's data/ directory
- Vertex Gemini can be called through LiteLLM
- the simulator preserves scenario state across turns
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

from dotenv import load_dotenv


ROOT = Path(__file__).resolve().parents[1]
TAU2_SRC = ROOT / "third_party" / "tau2-bench" / "src"


def _prepare_env() -> None:
    load_dotenv(dotenv_path=ROOT / ".env")
    os.environ.setdefault("TAU2_DATA_DIR", str(ROOT / "data"))
    os.environ.setdefault("VERTEXAI_PROJECT", os.getenv("PROJECT_ID", ""))
    os.environ.setdefault("VERTEXAI_LOCATION", "global")
    if str(TAU2_SRC) not in sys.path:
        sys.path.insert(0, str(TAU2_SRC))


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--task-id", default="0")
    parser.add_argument("--model", default="vertex_ai/gemini-3-flash-preview")
    parser.add_argument("--max-tokens", type=int, default=2048)
    args = parser.parse_args()

    _prepare_env()

    from tau2.data_model.message import AssistantMessage
    from tau2.domains.retail.environment import get_tasks
    from tau2.user.user_simulator import UserSimulator

    tasks = {task.id: task for task in get_tasks("base")}
    task = tasks[args.task_id]
    instructions = task.user_scenario.instructions.model_dump_json(indent=2)

    user = UserSimulator(
        llm=args.model,
        instructions=instructions,
        llm_args={"temperature": 0.0, "max_tokens": args.max_tokens},
    )
    state = user.get_init_state()

    first, state = user.generate_next_message(
        AssistantMessage(
            role="assistant",
            content=(
                "Hello, thank you for contacting customer support. "
                "How can I help you today?"
            ),
        ),
        state,
    )
    second, state = user.generate_next_message(
        AssistantMessage(
            role="assistant",
            content=(
                "I can help with that. Could you verify your name, zip code, "
                "and email address?"
            ),
        ),
        state,
    )

    print(f"task_id: {task.id}")
    print(f"model: {args.model}")
    print(f"turn1: {first.content}")
    print(f"turn2: {second.content}")
    print(f"turn1_usage: {first.usage}")
    print(f"turn2_usage: {second.usage}")
    print(f"turn1_cost: {first.cost}")
    print(f"turn2_cost: {second.cost}")


if __name__ == "__main__":
    main()
