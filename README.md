# CodeRAG Voice Engineer

A voice-first AI software-engineering platform: talk to an agent about a real
repository and get evidence-grounded answers (with file:line citations), backed by
tree-sitter code intelligence, hybrid (semantic + lexical) retrieval, a repository
call graph, and Git history — not a wrapper around "vector search + LLM."

**Status**: early, honest V1. See [docs/PROJECT_STATUS.md](docs/PROJECT_STATUS.md) for
exactly what's built, verified, and not yet built — updated continuously, no
fabricated claims.

## Quickstart

Backend (Python 3.14+):
```bash
cd apps/backend
python -m venv .venv
.venv/Scripts/pip install -r requirements.txt   # .venv/bin/pip on macOS/Linux
cp ../../.env.example ../../.env                 # add ANTHROPIC_API_KEY to use /chat
.venv/Scripts/python -m uvicorn main:app --reload --port 8000
```

Frontend (Node 20+):
```bash
cd apps/frontend
npm install
npm run dev -- -p 3100
```

Open http://localhost:3100, index a local repository by path, and ask it a question.
Retrieval (`/api/v1/search`) works with zero API keys (local `fastembed` embeddings).
The agent (`/api/v1/chat`) needs `ANTHROPIC_API_KEY` or `OPENAI_API_KEY`.

## Why this architecture

- **Code-aware, not token-window, chunking** — chunks are functions/classes/methods
  with real line ranges, so citations point at something a human can open and read.
- **Hybrid retrieval** (semantic + BM25, fused via RRF) because pure vector search
  misses exact identifier matches ("find `validate_token`") that lexical search nails.
- **A bounded agent loop**, not an unbounded ReAct loop — explicit max
  iterations/tool-calls/timeout and duplicate-call suppression, because unbounded
  agent loops are how you burn a token budget on nothing.
- **Evidence-first answers** (CONFIRMED/INFERRED/UNKNOWN) because an agent that always
  sounds confident is worse than useless for debugging.
- **No provider hardcoding** — LLM/embedding/voice providers are behind interfaces
  (`packages/shared/providers.py`) specifically so this isn't a single-vendor demo.

Full rationale for every non-obvious choice — including the ones forced by this
environment having no Docker/Postgres and no API keys — is in
[docs/DECISIONS.md](docs/DECISIONS.md) and [docs/INITIAL_AUDIT.md](docs/INITIAL_AUDIT.md).
Architecture diagrams: [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md).

## Repository layout

See [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md#directory-layout).

## Tests & evaluation

Run from the repo root:
```bash
apps/backend/.venv/Scripts/python -m pytest -q       # .venv/bin/python on macOS/Linux
apps/backend/.venv/Scripts/python evaluation/retrieval_benchmark.py
```
