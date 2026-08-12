# Architecture

## System overview

```mermaid
flowchart TD
    U[User: voice or text] --> UI[Next.js frontend]
    UI --> API[FastAPI backend /api/v1]
    API --> ORCH[Agent Orchestrator]
    ORCH --> RAG[Hybrid CodeRAG]
    ORCH --> GIT[Git Intelligence]
    ORCH --> GRAPH[Code Graph]
    ORCH --> SANDBOX[Code Sandbox]
    RAG --> VEC[(Chroma vector store)]
    RAG --> BM25[(BM25 lexical index)]
    RAG --> DB[(SQLite / Postgres: metadata, graph, git)]
    GRAPH --> DB
    GIT --> DB
    ORCH --> LLM[LLMProvider: Anthropic/OpenAI]
    UI --> STT[SpeechToTextProvider]
    UI --> TTS[TextToSpeechProvider]
```

## Repository indexing pipeline

```mermaid
flowchart LR
    R[Repository] --> V[Security validation]
    V --> FD[File discovery + language detect]
    FD --> P[tree-sitter parse]
    P --> SYM[Symbol/AST extraction]
    SYM --> CHUNK[Code-aware chunking]
    CHUNK --> EMB[Embed via EmbeddingProvider]
    CHUNK --> LEX[BM25 index]
    SYM --> GRAPH[Graph edges: calls/imports/inherits/tests]
    R --> GH[Git log/diff parse]
    GH --> DB[(store)]
    EMB --> DB
    LEX --> DB
    GRAPH --> DB
```

## Agent state machine (query/answer path)

```mermaid
stateDiagram-v2
    [*] --> UNDERSTAND
    UNDERSTAND --> PLAN
    PLAN --> RETRIEVE
    RETRIEVE --> ANALYZE
    ANALYZE --> RETRIEVE: needs more evidence (bounded)
    ANALYZE --> VERIFY
    VERIFY --> RESPOND
    RESPOND --> [*]
```

Action path (code modification) adds PROPOSE → AUTHORIZE (human gate) → MODIFY → TEST
→ VERIFY before RESPOND, per [module 32 of the spec]. Every agent run enforces
max_iterations, max_tool_calls, wall-clock timeout, and a token budget; repeated
identical tool calls abort the loop and force replanning.

## Data model (V1, SQLite; same schema targets Postgres)

`repositories`, `branches`, `commits`, `files`, `symbols`, `chunks`, `edges`
(graph: source_symbol_id, target_symbol_id, relation), `conversations`, `messages`,
`agent_runs`, `tool_calls`, `citations`. Migrations via Alembic.

## Directory layout

Matches spec section 92 (`apps/`, `packages/`, `workers/`, `infrastructure/`, `tests/`,
`evaluation/`, `docs/`, `scripts/`).

## Provider abstractions (`packages/shared/providers.py`)

`LLMProvider`, `EmbeddingProvider`, `RerankerProvider`, `SpeechToTextProvider`,
`TextToSpeechProvider` — all configured via environment variables, none hardcoded into
business logic. See [DECISIONS.md](DECISIONS.md) for default implementations.

## What is NOT built yet

Tracked honestly in [PROJECT_STATUS.md](PROJECT_STATUS.md) — do not infer completeness
from this document; it describes the target shape, not current state.
