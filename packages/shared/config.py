"""Environment-driven configuration. No secrets hardcoded, no secrets logged."""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

DATA_DIR = Path(os.environ.get("CODERAG_DATA_DIR", Path(__file__).resolve().parents[2] / "data"))
DATA_DIR.mkdir(parents=True, exist_ok=True)


@dataclass(frozen=True)
class Settings:
    sqlite_path: str = str(DATA_DIR / "coderag.db")
    chroma_path: str = str(DATA_DIR / "chroma")
    embedding_provider: str = os.environ.get("EMBEDDING_PROVIDER", "fastembed")
    llm_provider: str = os.environ.get("LLM_PROVIDER", "ollama")
    ollama_base_url: str = os.environ.get("OLLAMA_BASE_URL", "http://localhost:11434")
    ollama_model: str = os.environ.get("OLLAMA_MODEL", "qwen2.5:3b-instruct")
    anthropic_api_key: str | None = os.environ.get("ANTHROPIC_API_KEY")
    anthropic_model: str = os.environ.get("ANTHROPIC_MODEL", "claude-sonnet-4-5")
    openai_api_key: str | None = os.environ.get("OPENAI_API_KEY")
    max_agent_iterations: int = int(os.environ.get("CODERAG_MAX_ITERATIONS", "8"))
    max_tool_calls: int = int(os.environ.get("CODERAG_MAX_TOOL_CALLS", "12"))
    # Local CPU inference (Ollama) is much slower than a hosted API; 180s default
    # avoids the agent's own loop-protection firing on legitimately-slow generation.
    agent_timeout_seconds: int = int(os.environ.get("CODERAG_AGENT_TIMEOUT", "180"))
    sandbox_backend: str = os.environ.get("SANDBOX_BACKEND", "subprocess")


settings = Settings()
