"""Minimal model connectivity checks."""

from __future__ import annotations

from langchain_core.messages import HumanMessage

from cs263_agent_eval.config import settings
from cs263_agent_eval.model_factory import get_small_ollama_llm, get_vertex_llm


def _check(label: str, llm) -> None:
    response = llm.invoke([HumanMessage(content="Reply with exactly: CONNECTED")])
    print(f"{label}: {response.content}")


def main() -> None:
    print(f"PROJECT_ID: {'set' if settings.project_id else 'missing'}")
    print(f"GOOGLE_API_KEY: {'set' if settings.google_api_key else 'missing'}")
    print(f"Vertex model: {settings.large_vertex_model}")
    print(f"Ollama model: {settings.small_ollama_model}")

    _check("vertex", get_vertex_llm())
    _check("ollama", get_small_ollama_llm())


if __name__ == "__main__":
    main()
