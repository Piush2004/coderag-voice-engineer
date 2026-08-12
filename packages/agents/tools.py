"""Agent tools. All tools here are READ-only (spec module 24/25) — safe to run
without authorization. WRITE tools (apply_patch) and EXECUTE tools (run_tests) live in
packages/agents/code_agent.py behind an explicit authorization gate.
"""
from __future__ import annotations

from packages.rag.retrieval import hybrid_search
from packages.rag.store import ChunkRecord, CommitRecord, Edge, SymbolRecord, get_session

TOOL_SCHEMAS = [
    {
        "name": "search_code",
        "description": "Hybrid semantic+lexical search over the repository's code chunks. Use for open-ended questions about behavior, architecture, or 'where is X'.",
        "input_schema": {
            "type": "object",
            "properties": {"query": {"type": "string"}, "top_k": {"type": "integer", "default": 6}},
            "required": ["query"],
        },
    },
    {
        "name": "search_symbols",
        "description": "Find functions/classes/methods by (partial, case-insensitive) name.",
        "input_schema": {
            "type": "object",
            "properties": {"name_query": {"type": "string"}},
            "required": ["name_query"],
        },
    },
    {
        "name": "find_callers",
        "description": "List symbols that call the given function/method name (direct callers only).",
        "input_schema": {
            "type": "object",
            "properties": {"symbol_name": {"type": "string"}},
            "required": ["symbol_name"],
        },
    },
    {
        "name": "find_callees",
        "description": "List functions/methods called from within the given symbol.",
        "input_schema": {
            "type": "object",
            "properties": {"symbol_name": {"type": "string"}},
            "required": ["symbol_name"],
        },
    },
    {
        "name": "find_tests",
        "description": "Find test chunks (file path contains 'test') whose content references the given symbol name.",
        "input_schema": {
            "type": "object",
            "properties": {"symbol_name": {"type": "string"}},
            "required": ["symbol_name"],
        },
    },
    {
        "name": "search_git_history",
        "description": "Search commit messages and changed-file lists for a keyword (e.g. a symbol or file name).",
        "input_schema": {
            "type": "object",
            "properties": {"query": {"type": "string"}, "limit": {"type": "integer", "default": 10}},
            "required": ["query"],
        },
    },
    {
        "name": "inspect_file",
        "description": "Return all indexed chunks for a specific file path, ordered by line number.",
        "input_schema": {
            "type": "object",
            "properties": {"file_path": {"type": "string"}},
            "required": ["file_path"],
        },
    },
]


def execute_tool(repository_id: int, name: str, arguments: dict) -> dict:
    if name == "search_code":
        results = hybrid_search(repository_id, arguments["query"], top_k=arguments.get("top_k", 6))
        return {
            "results": [
                {
                    "file": r.file_path,
                    "symbol": r.symbol_name,
                    "lines": f"{r.line_start}-{r.line_end}",
                    "chunk_id": r.chunk_id,
                    "content": r.content,
                }
                for r in results
            ]
        }

    session = get_session()
    try:
        if name == "search_symbols":
            q = arguments["name_query"].lower()
            rows = (
                session.query(SymbolRecord)
                .filter(SymbolRecord.repository_id == repository_id)
                .filter(SymbolRecord.name.ilike(f"%{q}%"))
                .limit(20)
                .all()
            )
            return {
                "symbols": [
                    {
                        "name": s.name,
                        "kind": s.kind,
                        "parent": s.parent,
                        "file": s.file.path,
                        "lines": f"{s.line_start}-{s.line_end}",
                    }
                    for s in rows
                ]
            }
        if name == "find_callers":
            rows = (
                session.query(Edge)
                .filter_by(repository_id=repository_id, relation="calls", target=arguments["symbol_name"])
                .limit(30)
                .all()
            )
            return {"callers": [{"symbol": e.source, "file": e.source_file} for e in rows]}
        if name == "find_callees":
            rows = (
                session.query(Edge)
                .filter_by(repository_id=repository_id, relation="calls", source=arguments["symbol_name"])
                .limit(30)
                .all()
            )
            return {"callees": [{"symbol": e.target} for e in rows]}
        if name == "find_tests":
            sym = arguments["symbol_name"]
            rows = (
                session.query(ChunkRecord)
                .filter(ChunkRecord.repository_id == repository_id)
                .filter(ChunkRecord.file_path.ilike("%test%"))
                .filter(ChunkRecord.content.ilike(f"%{sym}%"))
                .limit(10)
                .all()
            )
            return {
                "tests": [
                    {"file": r.file_path, "symbol": r.symbol_name, "lines": f"{r.line_start}-{r.line_end}"}
                    for r in rows
                ]
            }
        if name == "search_git_history":
            q = arguments["query"]
            limit = arguments.get("limit", 10)
            rows = (
                session.query(CommitRecord)
                .filter(CommitRecord.repository_id == repository_id)
                .filter(
                    (CommitRecord.message.ilike(f"%{q}%")) | (CommitRecord.files_changed.ilike(f"%{q}%"))
                )
                .order_by(CommitRecord.committed_at.desc())
                .limit(limit)
                .all()
            )
            return {
                "commits": [
                    {
                        "sha": c.sha[:10],
                        "author": c.author,
                        "date": c.committed_at.isoformat() if c.committed_at else None,
                        "message": c.message,
                    }
                    for c in rows
                ]
            }
        if name == "inspect_file":
            rows = (
                session.query(ChunkRecord)
                .filter_by(repository_id=repository_id, file_path=arguments["file_path"])
                .order_by(ChunkRecord.line_start)
                .all()
            )
            return {
                "chunks": [
                    {"symbol": r.symbol_name, "type": r.chunk_type, "lines": f"{r.line_start}-{r.line_end}"}
                    for r in rows
                ]
            }
    finally:
        session.close()

    raise ValueError(f"Unknown tool: {name}")
