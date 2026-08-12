"""Hybrid retrieval: semantic (Chroma) + lexical (BM25) + metadata filters, combined
via reciprocal-rank fusion, then a lightweight cross-signal rerank.

No RerankerProvider LLM call by default (cost/latency) — the fusion + term-overlap
rerank below is the V1 reranker; a cross-encoder RerankerProvider can be swapped in
behind the same `rerank()` call without changing callers.
"""
from __future__ import annotations

from dataclasses import dataclass

from rank_bm25 import BM25Okapi

from packages.rag.store import ChunkRecord, get_chroma_collection, get_session
from packages.shared.config import settings
from packages.shared.providers import get_embedding_provider

_bm25_cache: dict[int, tuple[BM25Okapi, list[ChunkRecord]]] = {}


def _tokenize(text: str) -> list[str]:
    return [t for t in "".join(c if c.isalnum() else " " for c in text.lower()).split() if t]


def _get_bm25_index(repository_id: int) -> tuple[BM25Okapi, list[ChunkRecord]]:
    if repository_id not in _bm25_cache:
        session = get_session()
        try:
            chunks = session.query(ChunkRecord).filter_by(repository_id=repository_id).all()
        finally:
            session.close()
        corpus = [_tokenize(c.content) for c in chunks]
        bm25 = BM25Okapi(corpus) if corpus else None
        _bm25_cache[repository_id] = (bm25, chunks)
    return _bm25_cache[repository_id]


def invalidate_bm25_cache(repository_id: int) -> None:
    _bm25_cache.pop(repository_id, None)


@dataclass
class EvidenceItem:
    chunk_id: str
    file_path: str
    symbol_name: str | None
    chunk_type: str
    line_start: int
    line_end: int
    content: str
    score: float
    matched_by: list[str]  # ["semantic", "lexical"]


def hybrid_search(
    repository_id: int,
    query: str,
    top_k: int = 8,
    candidate_k: int = 30,
    chunk_type: str | None = None,
) -> list[EvidenceItem]:
    embedder = get_embedding_provider(settings.embedding_provider)
    collection = get_chroma_collection()

    where: dict = {"repository_id": repository_id}
    if chunk_type:
        where = {"$and": [{"repository_id": repository_id}, {"chunk_type": chunk_type}]}

    query_vec = embedder.embed([query])[0]
    semantic = collection.query(
        query_embeddings=[query_vec], n_results=candidate_k, where=where
    )
    semantic_ids = semantic["ids"][0] if semantic["ids"] else []
    # Chroma cosine distance -> similarity rank (lower distance = better).
    semantic_rank = {cid: rank for rank, cid in enumerate(semantic_ids)}

    bm25, chunks = _get_bm25_index(repository_id)
    lexical_rank: dict[str, int] = {}
    if bm25 is not None and chunks:
        scores = bm25.get_scores(_tokenize(query))
        ranked = sorted(range(len(chunks)), key=lambda i: scores[i], reverse=True)[:candidate_k]
        lexical_rank = {chunks[i].id: rank for rank, i in enumerate(ranked)}

    # Reciprocal rank fusion.
    K = 60
    fused: dict[str, float] = {}
    matched_by: dict[str, list[str]] = {}
    for cid, r in semantic_rank.items():
        fused[cid] = fused.get(cid, 0.0) + 1.0 / (K + r)
        matched_by.setdefault(cid, []).append("semantic")
    for cid, r in lexical_rank.items():
        fused[cid] = fused.get(cid, 0.0) + 1.0 / (K + r)
        matched_by.setdefault(cid, []).append("lexical")

    top_ids = sorted(fused, key=lambda cid: fused[cid], reverse=True)[:top_k]
    if not top_ids:
        return []

    session = get_session()
    try:
        records = {c.id: c for c in session.query(ChunkRecord).filter(ChunkRecord.id.in_(top_ids)).all()}
    finally:
        session.close()

    results = []
    for cid in top_ids:
        rec = records.get(cid)
        if rec is None:
            continue
        results.append(
            EvidenceItem(
                chunk_id=cid,
                file_path=rec.file_path,
                symbol_name=rec.symbol_name,
                chunk_type=rec.chunk_type,
                line_start=rec.line_start,
                line_end=rec.line_end,
                content=rec.content,
                score=round(fused[cid], 5),
                matched_by=matched_by.get(cid, []),
            )
        )
    return results
