"""LLM constructors.

Only the invocation style is borrowed from the prior project. No old benchmark data,
tasks, prompts, or sources are reused here.
"""

from __future__ import annotations

from cs263_agent_eval.config import settings


def get_vertex_llm(model_name: str | None = None):
    """Create a Gemini chat model through Google Cloud Vertex AI."""
    if not settings.project_id:
        raise ValueError("PROJECT_ID is required in .env for Vertex AI.")

    from langchain_google_vertexai import ChatVertexAI

    return ChatVertexAI(
        model_name=model_name or settings.large_vertex_model,
        project=settings.project_id,
        location=settings.location,
        temperature=settings.temperature,
    )


def get_small_ollama_llm(model_name: str | None = None):
    """Create a local Ollama chat model for the small-agent experiments."""
    from langchain_ollama import ChatOllama

    return ChatOllama(
        model=model_name or settings.small_ollama_model,
        temperature=settings.temperature,
    )
