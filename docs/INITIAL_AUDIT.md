# Initial Audit — 2026-08-13

## Environment
- OS: Windows 11, PowerShell + Git Bash both available
- Git: 2.54.0 (repo initialized fresh, was not a git repo)
- Python: 3.14.5 (very new; verified compatible with fastapi, sqlalchemy, chromadb,
  tree-sitter, tree-sitter-python/javascript, rank-bm25, fastembed — all installed clean)
- Node: 24.16.0 / npm 11.13.0
- Docker: **not installed**. No local Postgres/Redis daemon available.
- No API keys present in environment for Anthropic, OpenAI, ElevenLabs, Deepgram, Groq,
  Cohere. `ANTHROPIC_BASE_URL` is set (belongs to the Claude Code harness itself, not
  usable as an app credential).

## Consequences for architecture
1. **Local dev must run without Docker.** Postgres+pgvector is the documented
   production target (docker-compose provided), but the default local dev path uses
   SQLite (metadata/graph/relational) + Chroma (embedded vector store, persists to
   disk, no server process) + `rank_bm25` (lexical). This keeps V1 runnable with
   `pip install` only — no daemons required.
2. **Embeddings default to a local model** via `fastembed` (ONNX runtime, no torch,
   ~100MB, CPU-only, ~5s cold start) so retrieval works with zero API keys. An
   OpenAI/Voyage `EmbeddingProvider` implementation is included behind the same
   interface for teams that want higher-quality hosted embeddings.
3. **LLM reasoning, STT, and TTS require user-supplied API keys.** These are true
   external dependencies with no viable fully-local substitute at acceptable quality
   inside this environment. The app fails loudly with a clear setup message when keys
   are missing rather than silently stubbing responses. `.env.example` documents every
   required variable. Voice UI additionally supports the browser's native Web Speech
   API as a zero-config fallback so the voice loop is demonstrable without any STT/TTS
   provider key.
4. **No sandboxed container runtime available locally** for the code-execution /
   test-running agent. That agent is implemented against a `Sandbox` interface with a
   `subprocess`-based local backend (resource/time limits, temp workspace, no network)
   for this environment, and a documented Docker-backed backend for production use —
   swappable without changing the agent.

## Decision log
See [DECISIONS.md](DECISIONS.md).
