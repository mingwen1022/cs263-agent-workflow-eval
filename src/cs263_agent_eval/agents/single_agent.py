"""Single-agent baseline harnesses built on LangChain."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from langchain.agents import create_agent


def build_single_agent(model: Any, tools: Sequence[Any], system_prompt: str):
    """Build one ReAct-style tool-using agent with LangChain's current agent API."""
    return create_agent(
        model=model,
        tools=list(tools),
        system_prompt=system_prompt,
    )


def build_baseline_prompt(required_fields: list[str]) -> str:
    return (
        "You are solving a hard multi-step workflow task. Use the available tools "
        "to discover and inspect sources. Do not assume a source is sufficient until "
        "you have checked for conflicts, outdated information, exceptions, and required "
        "calculations. Keep evidence grounded in the retrieved sources. Return only "
        "valid JSON, with no markdown or extra commentary. Follow the output fields "
        "requested by the user task. "
        "For every array field, include only items that are directly and specifically "
        "supported by the sources — do not add items that are inferred, speculative, "
        "or not explicitly present in the evidence."
    )
