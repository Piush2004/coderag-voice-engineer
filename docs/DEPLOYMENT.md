# Deployment

**Status: not deployed. Docker configuration not built. This is an honest gap, not
an oversight** — see [INITIAL_AUDIT.md](INITIAL_AUDIT.md): this environment has no
Docker installed, so Docker Compose configuration could not be built *and tested*
here, and per project ground rules (spec module 94), nothing gets written that
claims to work without having been run.

## What would be needed (not yet done)

1. **Dockerfiles** for `apps/backend` (Python 3.14 + the packages in
   `apps/backend/requirements.txt`) and `apps/frontend` (Node 24, `next build`).
2. **docker-compose.yml** wiring: `backend`, `frontend`, and — if migrating off
   SQLite/Chroma per [DECISIONS.md](DECISIONS.md)'s documented production path —
   `postgres` (with pgvector) and optionally `redis` for a background indexing queue.
   Ollama can run as its own container (`ollama/ollama` image) or point
   `OLLAMA_BASE_URL` at a host-level instance.
3. **CI** (GitHub Actions): lint, `pytest`, `evaluation/retrieval_benchmark.py`
   (retrieval regression gate), frontend `npm run build`. Not built — no CI file
   exists in `.github/workflows/` yet.
4. **A real deployment target** — Anthropic/OpenAI-backed for a public demo (Ollama
   is a local-dev convenience, not something to expose publicly), a managed Postgres
   instance, and a host for the frontend (Vercel is the path of least resistance for
   Next.js). None of this has credentials or infrastructure available in this
   environment to actually provision and verify.

## What already works without Docker

The whole system runs today with no containers: `pip install` + `npm install`,
SQLite + Chroma + BM25 (no daemons), Ollama as a local process. See the Quickstart in
[README.md](../README.md). This was a deliberate design choice
([DECISIONS.md](DECISIONS.md)), not a workaround — it's also just a materially
simpler local dev story than requiring Docker for a project this size.
