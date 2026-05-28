"""Benchmark generation entry points.

Implementation note: generate new synthetic workflow data here. Do not import or
copy source content from the prior project.
"""

from __future__ import annotations

from cs263_agent_eval.schemas import BenchmarkTask


def generate_hard_tasks() -> list[BenchmarkTask]:
    """Generate the final 10 hard tasks.

    This is intentionally empty until the task worlds are implemented from the
    new blueprints in DEVELOPMENT_PLAN.md.
    """
    return []
