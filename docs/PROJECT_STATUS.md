# Project Status — 2026-08-13 (updated: Ollama integration + code modification agent)

Phase reference: [ARCHITECTURE.md](ARCHITECTURE.md) / [DECISIONS.md](DECISIONS.md).
This file is the source of truth for what's real vs. not yet built — see spec rule 94
("do not fake anything"). Nothing below is claimed without evidence in this repo.
Legend: **DONE** / **PARTIAL** / **NOT IMPLEMENTED** / **BLOCKED**.

## DONE — built, tested, verified end-to-end

- **Foundation.** Git repo, Python 3.14 venv, Node 24 frontend (Next.js 16/React 19).
- **Code intelligence.** tree-sitter parsing for **Python, JavaScript, TypeScript,
  and Go** (Go added this session — `packages/code_intelligence/parser.py`).
  Extracts classes/structs, functions, methods, imports, docstrings, call
  references. 6 parser unit tests passing, one per language's class/method/call
  extraction.
- **Ingestion.** `packages/rag/indexer.py` — path-traversal-safe, size-capped,
  binary-safe file discovery; code-aware chunking; call/import graph edges; Git log
  ingestion. **Secret redaction runs on every chunk before storage** (new this
  session — `packages/rag/secrets.py`, 7 tests, catches AWS/GitHub/Slack keys, PEM
  blocks, JWTs, DB connection strings, generic key/token/password assignments).
- **Hybrid retrieval.** Semantic (Chroma) + lexical (BM25) via reciprocal-rank
  fusion. Measured on the 6-query fixture: **Recall@5 = 1.00, MRR = 1.00** (small,
  self-authored — see [EVALUATION.md](EVALUATION.md)).
- **No overfitting to the CodeRAG codebase itself** — verified against 3 independent
  demo repos in `demo-repos/` (Python/FastAPI, TypeScript, Go), each indexed and
  retrieval-tested with correct top-1 results on natural-language queries (e.g. "how
  is the cart subtotal calculated" → `src/cart.ts::Cart.subtotal` in the TS repo).
- **Local LLM via Ollama — the headline addition this session.**
  `packages/shared/providers.py::OllamaProvider`, default `LLM_PROVIDER`, no API key
  required. Model: `qwen2.5:3b-instruct` (chosen after `nemotron-mini` — already
  installed — failed a direct tool-call test; see [OLLAMA.md](OLLAMA.md) for the full
  selection rationale). `GET /api/v1/health/llm` proactive health check.
  **The full agent loop was verified live and end-to-end**: FastAPI → agent
  orchestrator → Ollama → tool selection → tool execution → evidence → grounded
  answer with correct file:line citations. Example (real, not paraphrased): asked
  "Where is hybrid retrieval implemented?", the agent called `search_code`, and
  answered "...found in `packages/rag/retrieval.py`... [file:1:packages/rag/
  retrieval.py:hybrid_search:55-123]" — verified correct.
- **A real concurrency bug found and fixed during this testing**: two FastAPI
  threadpool threads racing to construct `chromadb.PersistentClient` on first
  access crashed chromadb's Rust bindings
  (`AttributeError: 'RustBindingsAPI' object has no attribute 'bindings'`). Fixed
  with a lock around the lazy singleton in `packages/rag/store.py`; regression test
  in `tests/rag/test_concurrent_chroma_init.py` reproduces it with 8 racing threads.
- **Code modification agent** (new this session — `packages/agents/code_agent.py`):
  investigate → propose patch → **explicit `authorized: true` gate** → isolated
  `git worktree` → apply → run tests in a subprocess sandbox → report diff. Real
  finding from live testing: the LLM's first patch attempt for unified-diff format
  was unreliable (small models struggle with diff syntax), so the design was changed
  to have the LLM output the corrected whole file and compute the diff with
  `difflib` instead — moving the hard part out of the model's hands. Even so, a live
  run against the real bug in `demo-repos/python-fastapi-app` produced a patch that
  silently dropped unrelated code (`Order` class, `calculate_total`) — **the system
  correctly did not report success**: it applied the patch, ran the real test suite
  in the sandbox, and reported `tests_passed: false` with the actual `ImportError`.
  This exact behavior (correct patch → tests pass; broken patch → tests correctly
  fail, never fabricated success) is locked in by 4 deterministic tests in
  `tests/rag/test_code_agent.py` that don't depend on live LLM output.
- **Security pass** (`docs/SECURITY.md` has the full breakdown): secret redaction
  (done, tested), path-traversal fuzzing (done, tested — symlink-escape test present
  but skipped on Windows, needs elevated privileges to create symlinks there),
  command-injection audit (done — only one `subprocess.run` call anywhere in
  `packages/`, fixed argv, no `shell=True`, no `eval`/`exec`), write-path
  authorization gate (done, tested). Sandbox isolation, auth/multi-tenancy, and rate
  limiting remain real gaps — see below.
- **Backend API additions**: `/api/v1/health/llm`, `/api/v1/fixes/propose`,
  `/api/v1/fixes/apply`.
- **Tests**: 26 passing, 1 skipped (Windows symlink privilege requirement) —
  `apps/backend/.venv/Scripts/python.exe -m pytest -q`.

## Real, measured local-model behavior (not idealized)

From `evaluation/adhoc_probe.py` (the exact 10 questions from the task brief, run
live against this repo — full output in git history / rerun anytime):

| Result | Count |
|---|---|
| Grounded answer with correct citations | 3/10 |
| Correctly said UNKNOWN after searching but not finding enough | 2/10 |
| Said UNKNOWN **without calling a tool first**, despite evidence existing | 4/10 |
| Vague/incomplete answer, 0 tool calls | 1/10 |

This is an honest, real limitation of a 3B-parameter CPU-inference model, not a bug
in the orchestrator (loop protection, tool execution, and citation extraction are
independently verified via direct tests). See [OLLAMA.md](OLLAMA.md) for detail and
the recommended fix (a larger local model, swappable via `OLLAMA_MODEL` with zero
code changes).

The larger 29-case categorized eval (`evaluation/agent_eval.py`, architecture/code-
nav/dependency/debugging/git/RAG/agent/security/no-answer/multi-hop) was run live
against this repository:

| Category | Result |
|---|---|
| architecture | 2/3 |
| code_navigation | 3/5 |
| dependency | 2/3 |
| debugging | 1/3 |
| git | 2/2 |
| rag | 1/3 |
| agent | 1/3 |
| security | 2/3 |
| no_answer | 2/2 |
| multi_hop | 2/2 |
| **Overall** | **18/29 (62%)** |

Full output in `evaluation/agent_eval_results.json` (includes every answer verbatim).
The first run of this eval scored 59% but was re-run after a real bug was found in
the *scorer itself*: it required `no_answer` cases to have zero citations, but
`citations` reflects every chunk `search_code` surfaced during investigation, not
claims actually made in the final answer — a correct "UNKNOWN" answer with prior
search activity was wrongly marked as a failure. Fixed; both `no_answer` cases now
correctly pass (verified live: asked "What is the production AWS account ID?", got
back exactly `"UNKNOWN"` — not a hallucination).

The real failures in the corrected run fall into two genuine patterns, not eval
artifacts:
1. **Skips tool use, answers from general knowledge or gives up** (~7 of 11
   failures) — e.g. asked "How does the agent avoid infinite tool-calling loops?", it
   answered with a generic description of how agents *typically* prevent loops
   (plausible-sounding, not wrong, but never looked at this repo's actual
   `max_iterations`/`max_tool_calls` logic — a real evidence-grounding failure, not a
   factual one).
2. **Wrong specific answer despite gathering evidence** (rarer, more concerning) —
   asked "Which function performs code-aware chunking?", it had 3 citations from a
   real search but answered `search_code` (the retrieval function) instead of
   `chunk_file` (the actual chunking function) — a genuine misattribution, not
   fabricated evidence but misread evidence.

Neither pattern is a bug in the orchestrator, evidence collection, or citation
extraction — all independently verified via deterministic tests. This is real,
measured behavior of a 3B-parameter CPU-inference model. See
[OLLAMA.md](OLLAMA.md) for the recommended next step (try a larger local model).

## NOT IMPLEMENTED (real gaps, explicit)

- **Server-side voice (STT/TTS providers)** — interfaces exist
  (`packages/shared/providers.py`), no concrete implementation. Browser Web Speech
  API fallback is real and working client-side. See
  [VOICE_ARCHITECTURE.md](VOICE_ARCHITECTURE.md).
- **Test generation agent, impact analysis agent, debugging agent** as distinct
  flows — the general query agent and the code modification agent's investigation
  step can answer these questions today, but there's no dedicated specialized
  workflow/prompt for each.
- **GitHub/upload/ZIP repository ingestion** — local filesystem paths only.
- **Auth, multi-tenancy, workspace isolation, rate limiting** — none. Single
  implicit user; anyone with network access to the API can index/query any local
  path the server can read. Required before any shared/networked deployment.
- **Background job queue for indexing** — synchronous in the request; fine for
  small/medium repos (demo repos indexed in 1-15s), would need Celery/RQ for very
  large ones or concurrent indexing.
- **Real container sandboxing** — the code-modification agent's test execution is a
  subprocess with a timeout, not a real security sandbox (no Docker in this
  environment — see [SECURITY.md](SECURITY.md)). Fine for running a repo's own
  tests; not safe against adversarial/untrusted repositories.
- **Postgres/pgvector, Redis, Docker, docker-compose, CI/CD, deployment** — not
  built; see [DEPLOYMENT.md](DEPLOYMENT.md) for exactly what's missing and why.
- **Reranker model, query rewriting, graph-based retrieval fusion beyond RRF.**
- **Observability UI, architecture graph visualization.**

## BLOCKED (needs something this environment doesn't have)

- Docker-backed sandbox and deployment: no Docker installed.
- Cloud STT/TTS and Anthropic/OpenAI-backed chat: no API keys present (Ollama
  removes the blocker for local dev/testing specifically; cloud providers remain
  optional and untested end-to-end here).

## Recommended next slice

1. Try a larger local model (`OLLAMA_MODEL=qwen2.5-coder:7b` or similar) to see if
   the "answers UNKNOWN without searching" failure mode improves — this is the
   single highest-leverage lever on answer quality right now.
2. Docker + docker-compose + CI (all documented as not-yet-built, not attempted
   without a way to verify them in this environment).
3. Auth/workspace isolation before any networked deployment.
4. A real container sandbox for code execution before running against untrusted
   repositories.
