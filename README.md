# CodeRAG Voice Engineer

A voice-first AI software-engineering platform: talk to an agent about a real
repository and get evidence-grounded answers (with file:line citations), backed by
tree-sitter code intelligence, hybrid (semantic + lexical) retrieval, a repository
call graph, and Git history — not a wrapper around "vector search + LLM."

**Status**: real, working, honestly-scoped. See [docs/PROJECT_STATUS.md](docs/PROJECT_STATUS.md)
for exactly what's built, verified, and not yet built (DONE/PARTIAL/NOT IMPLEMENTED/
BLOCKED) — updated continuously, no fabricated claims.

## Quickstart — fully local, zero API keys

Retrieval and the full agent both run with **no external API key** via
[Ollama](https://ollama.com) — see [docs/OLLAMA.md](docs/OLLAMA.md) for why and how
the local model was chosen.

```bash
ollama serve &                        # if not already running
ollama pull qwen2.5:3b-instruct       # ~1.9GB, one-time
```

Backend (Python 3.14+):
```bash
cd apps/backend
python -m venv .venv
.venv/Scripts/pip install -r requirements.txt   # .venv/bin/pip on macOS/Linux
cp ../../.env.example ../../.env                 # defaults already point at Ollama
.venv/Scripts/python -m uvicorn main:app --reload --port 8000
```

Frontend (Node 20+):
```bash
cd apps/frontend
npm install
npm run dev -- -p 3100
```

Open http://localhost:3100, index a local repository by path (try one of
`demo-repos/python-fastapi-app`, `demo-repos/typescript-app`,
`demo-repos/go-service` — small fixture repos included for exactly this), and ask it
a question. Prefer a hosted model instead? Set `LLM_PROVIDER=anthropic` +
`ANTHROPIC_API_KEY` in `.env`.

## What it can do today (verified live, not aspirational)

- Answer grounded, cited questions about a codebase via the full agent loop
  (investigate → tool calls → evidence → CONFIRMED/INFERRED/UNKNOWN answer).
- Propose and apply a code fix: `POST /api/v1/fixes/propose` (read-only investigation
  + patch proposal) → `POST /api/v1/fixes/apply` with `authorized: true` (isolated
  git worktree → apply patch → run real tests in a sandbox → report the diff and
  pass/fail — never claims success without actually running tests).
- Voice in the browser (push-to-talk, live transcript, spoken answers) via the Web
  Speech API — no server-side voice provider needed for this.

See [docs/PROJECT_STATUS.md](docs/PROJECT_STATUS.md) for real measured behavior of
the local model (it's a 3B CPU model — genuinely useful, not flawless; the honest
numbers are there) and everything not yet built.

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
