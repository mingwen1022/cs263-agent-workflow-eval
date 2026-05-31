"""Load hard benchmark tasks from data files."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from cs263_agent_eval.schemas import BenchmarkTask


PROJECT_ROOT = Path(__file__).resolve().parents[3]
GENERATED_ROOT = PROJECT_ROOT / "data" / "generated"
DATA_ROOT = GENERATED_ROOT / "hard_v1"
TASK_ROOT = DATA_ROOT / "tasks"


def _read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _hard_data_roots() -> list[Path]:
    return sorted(path for path in GENERATED_ROOT.glob("hard_v*") if path.is_dir())


def _task_path(task_id: str) -> Path:
    matches = [root / "tasks" / f"{task_id}.json" for root in _hard_data_roots()]
    existing = [path for path in matches if path.exists()]
    if not existing:
        raise FileNotFoundError(f"Hard task '{task_id}' not found in {GENERATED_ROOT}/hard_v*/tasks")
    if len(existing) > 1:
        raise ValueError(f"Hard task '{task_id}' exists in multiple hard_v* directories: {existing}")
    return existing[0]


def _load_sources(data_root: Path, source_manifest: str) -> dict[str, str]:
    manifest_path = data_root / source_manifest
    manifest = _read_json(manifest_path)
    source_dir = manifest_path.parent
    return {
        source_id: str(source_dir / filename)
        for source_id, filename in manifest.items()
    }


def load_hard_task(task_id: str) -> BenchmarkTask:
    path = _task_path(task_id)
    data_root = path.parents[1]
    task_spec = _read_json(path)
    source_manifest = task_spec.pop("source_manifest")
    task_spec["sources"] = _load_sources(data_root, source_manifest)
    return BenchmarkTask.model_validate(task_spec)


def list_hard_task_ids() -> list[str]:
    task_paths = []
    for data_root in _hard_data_roots():
        task_paths.extend((data_root / "tasks").glob("*.json"))
    return sorted(path.stem for path in task_paths)


def load_all_hard_tasks() -> list[BenchmarkTask]:
    return [load_hard_task(task_id) for task_id in list_hard_task_ids()]


def get_initial_hard_task() -> BenchmarkTask:
    return load_hard_task("hard_initial_tr19_reimbursement")
