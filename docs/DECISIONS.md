# Technical Decisions

## Backend language/framework
**Decision:** Python 3.14 + FastAPI + Pydantic v2 + SQLAlchemy 2.0
**Why:** Best ecosystem for tree-sitter bindings, embedding/reranking libs, and LLM
SDKs. FastAPI gives async I/O (needed for streaming voice/LLM) and free OpenAPI docs.
**Alternatives considered:** Node/TypeScript backend (unify with frontend language).
**Rejected because:** Python's code-intelligence and ML tooling (tree-sitter,
sentence embeddings, BM25, numpy) is materially more mature; a polyglot split
(TS frontend, Python backend) is standard for this class of system.

## Datastore for V1 (local dev)
**Decision:** SQLite (relational + graph edges) + Chroma (embedded vector store) +
`rank_bm25` (lexical), all file-backed, zero daemons.
**Why:** Environment has no Docker/Postgres available ([INITIAL_AUDIT.md](INITIAL_AUDIT.md)).
The system must be runnable with `pip install -r requirements.txt` alone.
**Production target:** PostgreSQL + pgvector, documented in `docker-compose.yml` and
`infrastructure/`, using the same repository interfaces (`packages/rag/store.py`) so
swapping backends is a config change, not a rewrite.
**Alternatives considered:** Qdrant, Pinecone, Weaviate (vector DBs); Neo4j (graph DB).
**Rejected because:** Extra infra for a codebase-scale graph that fits comfortably in
relational adjacency-list tables; standalone vector DBs add an operational dependency
pgvector avoids once Postgres is already required for relational data.

## Embeddings
**Decision:** `fastembed` (BAAI/bge-small-en-v1.5, ONNX, CPU, no API key) as default
`EmbeddingProvider`; OpenAI/Voyage implementations behind the same interface.
**Why:** RAG must work out of the box with no credentials for the demo to be
self-contained; `fastembed` avoids the multi-GB torch dependency of
sentence-transformers while giving competitive retrieval quality for code+prose.
**Alternatives considered:** `sentence-transformers` (torch, heavier), OpenAI
`text-embedding-3-small` (requires key, has per-token cost), Voyage `voyage-code-2`
(code-specialized, requires key).
**Rejected default:** hosted-only embeddings — would make the platform unusable
without a paid key, failing the "runs locally" requirement.

## LLM reasoning
**Decision:** Provider-abstracted `LLMProvider`; Anthropic Claude as the reference
implementation (system is being built inside Claude Code; Claude models are strong at
code reasoning and tool-use), OpenAI-compatible implementation included.
**Why:** No provider should be hardcoded into agent/prompt logic.
**Constraint:** No API key is present in this environment, so live LLM calls cannot be
exercised end-to-end here. The user must supply `ANTHROPIC_API_KEY` (or
`OPENAI_API_KEY`) via `.env` to run the agent live; this is documented, not faked.

## Code parsing
**Decision:** `tree-sitter` with per-language grammars (`tree-sitter-python`,
`tree-sitter-javascript`/`typescript` first; abstraction supports adding Java/Go/C++/C#
grammars later without redesign).
**Why:** Industry-standard incremental parser, uniform query API across languages,
fast enough for repo-scale ingestion.

## Code execution sandbox
**Decision:** `Sandbox` interface; local backend = `subprocess` with cwd isolated to a
temp worktree, wall-clock timeout, no network flag (best-effort on Windows), resource
caps where the OS allows. Docker backend documented for production (real filesystem/
network isolation).
**Why:** No Docker available locally ([INITIAL_AUDIT.md](INITIAL_AUDIT.md)); the
interface boundary means production deployments get real container isolation without
touching agent code.

## Voice
**Decision:** Provider-abstracted `SpeechToTextProvider`/`TextToSpeechProvider`
(Deepgram/ElevenLabs reference implementations, streaming); browser
`SpeechRecognition`/`speechSynthesis` Web APIs as a zero-key fallback used by the
frontend when no provider key is configured server-side.
**Why:** Demonstrable voice loop without requiring paid STT/TTS keys in this
environment, while keeping a real streaming-provider path for production quality.

## Orchestration
**Decision:** Hand-rolled explicit agent state machine (UNDERSTAND → PLAN → RETRIEVE →
ANALYZE → VERIFY → RESPOND), not LangGraph.
**Why:** The state machine is small and fully specified by this project's own spec;
adding LangGraph as a dependency buys abstraction we don't need yet and obscures loop-
protection/token-budget logic that must be auditable. Revisit if multi-agent branching
complexity grows.

## Monorepo tooling
**Decision:** Plain npm workspaces (frontend) + Python venv per app (no Turborepo/Nx,
no Poetry/uv) for V1.
**Why:** Minimizes tooling surface while the project is small; nothing here needs a
build-graph tool yet.
