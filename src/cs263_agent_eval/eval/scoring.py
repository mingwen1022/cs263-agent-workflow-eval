"""Deterministic scoring utilities for structured outputs."""

from __future__ import annotations

from typing import Any

import re

from cs263_agent_eval.schemas import BenchmarkTask, ScoreBreakdown


def _normalize_label(value: Any) -> str:
    text = str(value).strip().lower()
    text = re.sub(r"[^a-z0-9]+", "_", text)
    return re.sub(r"_+", "_", text).strip("_")


def _field_matches(expected: Any, actual: Any, tolerance: float | None = None) -> bool:
    if tolerance is not None:
        try:
            return abs(float(expected) - float(actual)) <= tolerance
        except (TypeError, ValueError):
            return False
    if isinstance(expected, str) and isinstance(actual, str):
        return _normalize_label(expected) == _normalize_label(actual)
    return expected == actual


def _normalize_set_value(value: Any) -> set[str]:
    if value is None:
        return set()
    if isinstance(value, str):
        return {_normalize_label(value)}
    if isinstance(value, list | tuple | set):
        return {_normalize_label(item) for item in value}
    return {_normalize_label(value)}


def _canonicalize_set_items(
    field: str,
    values: set[str],
    aliases: dict[str, dict[str, list[str]]],
) -> tuple[set[str], set[str]]:
    """Return (canonical_items, unexpected_items)."""
    if field not in aliases:
        return set(values), set()

    alias_lookup: dict[str, str] = {}
    for canonical, accepted in aliases.get(field, {}).items():
        canonical_label = _normalize_label(canonical)
        alias_lookup[canonical_label] = canonical_label
        for alias in accepted:
            alias_lookup[_normalize_label(alias)] = canonical_label

    canonical_items: set[str] = set()
    unexpected_items: set[str] = set()
    for value in values:
        if value in alias_lookup:
            canonical_items.add(alias_lookup[value])
        else:
            unexpected_items.add(value)
    return canonical_items, unexpected_items


def score_prediction(task: BenchmarkTask, answer: dict[str, Any]) -> ScoreBreakdown:
    criteria = task.evaluation_criteria
    checks: list[dict[str, Any]] = []

    for field in criteria.exact_fields:
        tolerance = criteria.numeric_tolerances.get(field)
        correct = _field_matches(
            task.gold_output.get(field),
            answer.get(field),
            tolerance,
        )
        checks.append(
            {
                "check_id": f"{field}.exact",
                "field": field,
                "type": "exact",
                "correct": correct,
                "expected": task.gold_output.get(field),
                "actual": answer.get(field),
            }
        )

    for field in criteria.set_fields:
        expected_raw = _normalize_set_value(task.gold_output.get(field))
        actual_raw = _normalize_set_value(answer.get(field))
        expected, _ = _canonicalize_set_items(field, expected_raw, criteria.set_aliases)
        actual, unexpected = _canonicalize_set_items(field, actual_raw, criteria.set_aliases)

        for expected_item in sorted(expected):
            checks.append(
                {
                    "check_id": f"{field}.contains.{expected_item}",
                    "field": field,
                    "type": "set_contains",
                    "correct": expected_item in actual,
                    "expected": expected_item,
                    "actual": sorted(actual),
                }
            )

        checks.append(
            {
                "check_id": f"{field}.no_unexpected_items",
                "field": field,
                "type": "set_no_unexpected_items",
                "correct": not unexpected and actual.issubset(expected),
                "expected": sorted(expected),
                "actual": sorted(actual),
                "unexpected": sorted(unexpected | (actual - expected)),
            }
        )

    total_checks = len(checks)
    correct_checks = sum(1 for check in checks if check["correct"])
    field_accuracy = correct_checks / total_checks if total_checks else 0.0
    return ScoreBreakdown(
        field_accuracy=field_accuracy,
        score_percent=round(field_accuracy * 100, 2),
        task_success=1.0 if correct_checks == total_checks and total_checks > 0 else 0.0,
        details={
            "correct_checks": correct_checks,
            "total_checks": total_checks,
            "checks": checks,
        },
    )
