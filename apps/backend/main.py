"""FastAPI entrypoint. Run: uvicorn apps.backend.main:app --reload --port 8000"""
from __future__ import annotations

import sys
import time
import traceback
import uuid
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Optional

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from packages.agents.code_agent import apply_fix, get_diff, get_proposal, investigate_and_propose, store_proposal
from packages.agents.state_machine import run_agent
from packages.rag.indexer import index_repository
from packages.rag.retrieval import hybrid_search, invalidate_bm25_cache
from packages.rag.store import Conversation, Message, Repository, get_session, init_db
from packages.shared.config import settings
from packages.shared.providers import OllamaProvider, ProviderNotConfiguredError


@asynccontextmanager
async def _lifespan(app: FastAPI):
    init_db()
    yield


app = FastAPI(title="CodeRAG Voice Engineer API", version="0.1.0", lifespan=_lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000", "http://localhost:3100"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.exception_handler(Exception)
async def unhandled_exception_handler(request, exc: Exception):
    from fastapi.responses import JSONResponse

    request_id = str(uuid.uuid4())
    print(f"[{request_id}] Unhandled error: {exc}\n{traceback.format_exc()}")
    return JSONResponse(
        status_code=500,
        content={"error": "internal_error", "request_id": request_id, "message": str(exc)},
    )


class RepositoryIn(BaseModel):
    name: str
    root_path: str


class RepositoryOut(BaseModel):
    id: int
    name: str
    root_path: str


@app.get("/api/v1/health")
def health():
    return {"status": "ok"}


@app.get("/api/v1/health/llm")
def llm_health():
    """Proactive provider health check — the UI calls this so a user finds out
    Ollama/the configured LLM is unavailable before sending a chat message, not after
    (spec module 5)."""
    if settings.llm_provider == "ollama":
        provider = OllamaProvider(base_url=settings.ollama_base_url, model=settings.ollama_model)
        return provider.health_check(ping=True)
    return {
        "provider": settings.llm_provider,
        "status": "configured" if (settings.anthropic_api_key or settings.openai_api_key) else "not_configured",
    }


@app.post("/api/v1/repositories", response_model=dict)
def create_repository(body: RepositoryIn):
    """Register + synchronously index a local repository path.

    V1 supports local filesystem paths only (see docs/PROJECT_STATUS.md — GitHub/
    upload ingestion is not yet implemented). Indexing is synchronous for now;
    background job queueing (spec module 53) is documented as a known limitation for
    repos beyond a few thousand files.
    """
    root = Path(body.root_path)
    if not root.exists():
        raise HTTPException(400, f"Path does not exist: {body.root_path}")
    try:
        result = index_repository(body.name, body.root_path)
    except ValueError as e:
        raise HTTPException(400, str(e))
    return result


@app.get("/api/v1/repositories")
def list_repositories():
    session = get_session()
    try:
        repos = session.query(Repository).all()
        return [{"id": r.id, "name": r.name, "root_path": r.root_path} for r in repos]
    finally:
        session.close()


class SearchQuery(BaseModel):
    repository_id: int
    query: str
    top_k: int = 8


@app.post("/api/v1/search")
def search(body: SearchQuery):
    """Direct hybrid retrieval, no LLM — used by the code explorer and for debugging
    retrieval quality independent of agent reasoning."""
    results = hybrid_search(body.repository_id, body.query, top_k=body.top_k)
    return {
        "results": [
            {
                "file": r.file_path,
                "symbol": r.symbol_name,
                "chunk_type": r.chunk_type,
                "lines": [r.line_start, r.line_end],
                "score": r.score,
                "matched_by": r.matched_by,
                "content": r.content,
            }
            for r in results
        ]
    }


class ChatIn(BaseModel):
    repository_id: int
    message: str
    conversation_id: Optional[int] = None


@app.post("/api/v1/chat")
def chat(body: ChatIn):
    session = get_session()
    try:
        if body.conversation_id:
            conv = session.get(Conversation, body.conversation_id)
            if conv is None:
                raise HTTPException(404, "conversation not found")
        else:
            conv = Conversation(repository_id=body.repository_id)
            session.add(conv)
            session.commit()
            session.refresh(conv)

        session.add(Message(conversation_id=conv.id, role="user", content=body.message))
        session.commit()
    finally:
        session.close()

    t0 = time.monotonic()
    try:
        result = run_agent(body.repository_id, conv.id, body.message)
    except ProviderNotConfiguredError as e:
        raise HTTPException(503, str(e))
    latency_ms = int((time.monotonic() - t0) * 1000)

    session = get_session()
    try:
        session.add(Message(conversation_id=conv.id, role="assistant", content=result.answer))
        session.commit()
    finally:
        session.close()

    return {
        "conversation_id": conv.id,
        "answer": result.answer,
        "citations": result.citations,
        "trace": result.trace,
        "status": result.status,
        "latency_ms": latency_ms,
    }


@app.post("/api/v1/repositories/{repository_id}/reindex")
def reindex(repository_id: int):
    session = get_session()
    try:
        repo = session.get(Repository, repository_id)
        if repo is None:
            raise HTTPException(404, "repository not found")
        root_path, name = repo.root_path, repo.name
    finally:
        session.close()
    invalidate_bm25_cache(repository_id)
    return index_repository(name, root_path)


class ProposeFixIn(BaseModel):
    repository_id: int
    instruction: str


@app.post("/api/v1/fixes/propose")
def propose_fix(body: ProposeFixIn):
    """READ-only investigation + patch proposal. Never touches disk (spec module 32) —
    apply_fix (below) is a separate call that requires explicit `authorized: true`."""
    session = get_session()
    try:
        conv = Conversation(repository_id=body.repository_id)
        session.add(conv)
        session.commit()
        session.refresh(conv)
    finally:
        session.close()
    try:
        proposal = investigate_and_propose(body.repository_id, conv.id, body.instruction)
    except ProviderNotConfiguredError as e:
        raise HTTPException(503, str(e))
    proposal_id = store_proposal(proposal)
    return {
        "conversation_id": conv.id,
        "proposal_id": proposal_id,
        "diagnosis": proposal.diagnosis,
        "citations": proposal.citations,
        "patch": proposal.patch,
        "confident": proposal.confident,
    }


class ApplyFixIn(BaseModel):
    repository_id: int
    proposal_id: str
    authorized: bool  # required, no default — caller must explicitly opt in


@app.post("/api/v1/fixes/apply")
def apply_fix_endpoint(body: ApplyFixIn):
    """WRITE + EXECUTE path. `authorized` must be true — this is the human-in-the-loop
    gate from spec module 32/64; there is no route that applies a patch without it.

    The patch is looked up server-side by `proposal_id` from what
    investigate_and_propose actually produced — it is never accepted as free-form
    text from the client. Without this, `authorized: true` would just be a boolean
    the caller sets on themselves, and a client could POST an arbitrary hand-written
    diff straight to this endpoint, which then runs auto-detected test commands via
    the sandbox (found in code review: an unauthenticated RCE primitive)."""
    if not body.authorized:
        raise HTTPException(400, "authorized must be true to apply a code change.")

    proposal = get_proposal(body.proposal_id)
    if proposal is None:
        raise HTTPException(404, "Unknown proposal_id — call /api/v1/fixes/propose first.")
    if proposal.repository_id != body.repository_id:
        raise HTTPException(400, "proposal_id does not belong to the given repository_id.")

    result = apply_fix(body.repository_id, proposal)
    diff = get_diff(result.worktree_path) if result.worktree_path else None
    return {
        "applied": result.applied,
        "branch": result.branch,
        "worktree_path": result.worktree_path,
        "tests_passed": result.tests_passed,
        "test_output": result.test_output,
        "diff": diff,
        "trace": result.trace,
        "error": result.error,
    }
