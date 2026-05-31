"""Load medium benchmark tasks from data files."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from cs263_agent_eval.schemas import BenchmarkTask


PROJECT_ROOT = Path(__file__).resolve().parents[3]
DATA_ROOT = PROJECT_ROOT / "data" / "generated" / "medium_v1"
TASK_ROOT = DATA_ROOT / "tasks"


def _read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _load_sources(source_manifest: str) -> dict[str, str]:
    manifest_path = DATA_ROOT / source_manifest
    manifest = _read_json(manifest_path)
    source_dir = manifest_path.parent
    return {
        source_id: str(source_dir / filename)
        for source_id, filename in manifest.items()
    }


def load_medium_task(task_id: str) -> BenchmarkTask:
    task_spec = _read_json(TASK_ROOT / f"{task_id}.json")
    source_manifest = task_spec.pop("source_manifest")
    task_spec["sources"] = _load_sources(source_manifest)
    return BenchmarkTask.model_validate(task_spec)


def list_medium_task_ids() -> list[str]:
    return sorted(path.stem for path in TASK_ROOT.glob("*.json"))


def load_all_medium_tasks() -> list[BenchmarkTask]:
    return [load_medium_task(task_id) for task_id in list_medium_task_ids()]
