# Project Status — 2026-08-13

Phase reference: [ARCHITECTURE.md](ARCHITECTURE.md) / [DECISIONS.md](DECISIONS.md).
This file is the source of truth for what's real vs. not yet built — see spec rule 94
("do not fake anything"). Nothing below is claimed without evidence in this repo.

## Done (built, tested, verified end-to-end)

- **Phase 0–2 — Foundation.** Repo scaffolded, git initialized, Python 3.14 venv
  (`apps/backend/.venv`) with all core deps installed and import-verified. Node 24
  frontend scaffolded (Next.js 16 / React 19 / Tailwind 4).
- **Phase 4–6 — Ingestion & code intelligence.** `packages/code_intelligence/parser.py`
  — real tree-sitter parsing for Python/JS/TS, extracting classes/functions/methods,
  imports, docstrings, and call references. `packages/rag/indexer.py` walks a repo
  (path-traversal-safe, size-capped, binary-safe), parses, builds a code graph
  (`calls`/`imports` edges in SQLite), pulls Git log via `git log --name-only` when
  `.git` exists, and embeds every chunk into Chroma. **Verified**: indexed this
  repository itself (20 files, 15 parsed, 99 chunks) and a synthetic fixture repo, in
  ~15s cold (dominated by one-time fastembed model download).
- **Phase 7 — Hybrid retrieval.** `packages/rag/retrieval.py` — semantic (Chroma) +
  lexical (BM25) fused via reciprocal-rank fusion, metadata filtering by chunk type.
  **Measured** on a 6-query fixture benchmark
  (`evaluation/retrieval_benchmark.py`): **Recall@5 = 1.00, MRR = 1.00** (n=6 — small
  and self-authored; not a claim of production-scale accuracy).
- **Phase 8 — Agent orchestration.** `packages/agents/state_machine.py` — bounded
  tool-calling loop (max iterations/tool calls/timeout, duplicate-call suppression),
  evidence-first system prompt (CONFIRMED/INFERRED/UNKNOWN), explicit prompt-injection
  instruction telling the model retrieved content is data not commands. Seven READ
  tools in `packages/agents/tools.py` (`search_code`, `search_symbols`,
  `find_callers`, `find_callees`, `find_tests`, `search_git_history`, `inspect_file`)
  — **verified** directly against real indexed data (correct results, correct
  file:line citations).
- **Backend API.** FastAPI app (`apps/backend/main.py`): `/api/v1/health`,
  `/repositories` (register+index), `/search` (retrieval only, no LLM),
  `/chat` (full agent loop), `/repositories/{id}/reindex`. Global exception handler
  returns a request ID instead of leaking stack traces. **Verified** live via curl and
  via the browser through the real frontend.
- **Frontend.** Next.js voice console (`apps/frontend/app/page.tsx`): repo
  index/select, chat transcript, citations, agent trace ("Searching code for...",
  etc. — no chain-of-thought exposure per spec rule 87), push-to-talk mic using the
  browser Web Speech API, TTS via `speechSynthesis`, interrupt/stop button.
  **Verified** in-browser end-to-end: indexed this repo through the UI, sent a chat
  message, got the correct, honest error (see below) rendered with no crash.
- **Tests.** 9 real pytest tests (`tests/unit`, `tests/rag`) covering parser, chunker,
  and a full index→retrieve integration path against an isolated temp DB. **All
  passing** (`apps/backend/.venv/Scripts/python.exe -m pytest -q` → `9 passed`).

## Explicitly NOT working / NOT built yet

- **LLM calls are untested end-to-end.** No `ANTHROPIC_API_KEY`/`OPENAI_API_KEY` is
  available in this environment ([INITIAL_AUDIT.md](INITIAL_AUDIT.md)). The full
  `/api/v1/chat` path is wired and returns a correct, honest 503
  ("ANTHROPIC_API_KEY is not set...") rather than a fabricated answer. Add a key to
  `.env` to exercise it live.
- **Server-side streaming STT/TTS** (Deepgram/ElevenLabs providers) — interfaces
  exist in `docs/DECISIONS.md`'s plan but are not implemented; only the browser
  Web Speech fallback is wired into the frontend today.
- **Code modification agent** (propose → authorize → patch → test → verify), **test
  generation agent**, **impact analysis agent**, **bug investigation agent** as
  distinct flows — not built. The general query agent can answer these questions via
  its tools today but there's no dedicated PROPOSE/AUTHORIZE/MODIFY state, no
  `Sandbox` execution backend, no patch/diff generation.
- **GitHub/upload repository ingestion** — only local filesystem paths are supported.
- **Auth, multi-tenancy, workspaces** — not built; single implicit user, no login.
- **Background job queue for indexing** — indexing is currently synchronous in the
  request; fine for small repos, will time out on very large ones.
- **Postgres/pgvector, Redis, Docker, docker-compose, CI/CD** — not built; V1 runs on
  SQLite+Chroma+BM25 with no daemons (see [DECISIONS.md](DECISIONS.md)). Docker
  wasn't available in this environment to build/test against.
- **Security hardening pass** (prompt-injection red-teaming, secret redaction,
  path-traversal fuzzing beyond the basic checks in `indexer.py`, rate limiting) —
  not done.
- **Reranker model, query rewriting, graph-based retrieval fusion** — RRF fusion of
  semantic+lexical is the only ranking signal today; no cross-encoder reranker or
  LLM-based query rewriting yet.
- **Evaluation dataset** is a 6-query synthetic fixture, not the "easy/medium/hard/
  multi-hop/adversarial" benchmark the full spec calls for.
- **Observability UI, deployment, architecture graph visualization** — not built.

## Recommended next slice

1. User supplies `ANTHROPIC_API_KEY` in `.env` → verify the live agent loop end-to-end
   (this is the highest-value next step; everything else is built assuming it works).
2. Code modification agent (propose/authorize/patch/test/verify) with a subprocess
   sandbox.
3. Expand the eval benchmark and add a security pass (prompt-injection tests,
   secret-redaction tests).
4. Docker Compose + Postgres/pgvector swap, CI workflow.
