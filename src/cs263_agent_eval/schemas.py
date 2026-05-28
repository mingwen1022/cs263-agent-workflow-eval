"""Shared schemas for tasks, outputs, and experiment records."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field


Difficulty = Literal["hard"]
TaskFamily = Literal["document_workflow", "multi_app_workflow"]
SystemName = Literal["large_single", "small_single", "small_agentic_workflow"]


class EvalCriteria(BaseModel):
    exact_fields: list[str] = Field(default_factory=list)
    numeric_tolerances: dict[str, float] = Field(default_factory=dict)
    set_fields: list[str] = Field(default_factory=list)
    set_aliases: dict[str, dict[str, list[str]]] = Field(default_factory=dict)
    evidence_fields: list[str] = Field(default_factory=list)
    required_tool_calls: list[str] = Field(default_factory=list)
    scoring_notes: str = ""


class BenchmarkTask(BaseModel):
    task_id: str
    task_family: TaskFamily
    difficulty: Difficulty = "hard"
    instruction: str
    allowed_tools: list[str]
    sources: dict[str, Any] = Field(default_factory=dict)
    gold_output: dict[str, Any]
    evaluation_criteria: EvalCriteria


class AgentPrediction(BaseModel):
    answer: dict[str, Any] = Field(default_factory=dict)
    evidence: list[dict[str, Any]] = Field(default_factory=list)
    tool_log: list[dict[str, Any]] = Field(default_factory=list)
    notes: str = ""


class ScoreBreakdown(BaseModel):
    field_accuracy: float
    score_percent: float
    evidence_accuracy: float | None = None
    tool_coverage: float | None = None
    details: dict[str, Any] = Field(default_factory=dict)


class RunRecord(BaseModel):
    task_id: str
    system_name: SystemName
    prediction: AgentPrediction
    scores: ScoreBreakdown | None = None
    latency_sec: float | None = None
    cost_usd: float | None = None
    error: str | None = None
