"""Project configuration and model factory settings."""

from __future__ import annotations

import os
from dataclasses import dataclass

from dotenv import load_dotenv

load_dotenv()


@dataclass(frozen=True)
class Settings:
    project_id: str = os.getenv("PROJECT_ID", "")
    google_api_key: str = os.getenv("GOOGLE_API_KEY", "")
    location: str = os.getenv("LOCATION", "us-central1")
    large_vertex_model: str = os.getenv("LARGE_VERTEX_MODEL", "gemini-2.5-flash")
    alternate_vertex_model: str = os.getenv("ALTERNATE_VERTEX_MODEL", "gemini-2.0-flash-001")
    small_ollama_model: str = os.getenv("SMALL_OLLAMA_MODEL", "gemma4:e4b")
    temperature: float = float(os.getenv("MODEL_TEMPERATURE", "0"))
    max_agent_steps: int = int(os.getenv("MAX_AGENT_STEPS", "20"))
    max_workflow_revisions: int = int(os.getenv("MAX_WORKFLOW_REVISIONS", "1"))


settings = Settings()
