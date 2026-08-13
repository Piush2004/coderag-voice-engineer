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
    {
        "name": "analyze_impact",
        "description": "Impact analysis for 'what breaks if I change X': direct callers, indirect (one-hop) callers, callees, and tests referencing the symbol, plus a risk level. Use for impact-analysis and refactoring-safety questions.",
        "input_schema": {
            "type": "object",
            "properties": {"symbol_name": {"type": "string"}},
            "required": ["symbol_name"],
        },
    },
    {
        "name": "co_changed_files",
        "description": "Git history: files that historically changed in the same commits as the given file — useful for 'what else usually changes with this file' questions.",
        "input_schema": {
            "type": "object",
            "properties": {"file_path": {"type": "string"}, "limit": {"type": "integer", "default": 8}},
            "required": ["file_path"],
        },
    },
]


class ToolArgumentError(ValueError):
    """Raised for a missing/invalid required argument. Message is written to be fed
    straight back to the LLM as a tool-result error (state_machine.py) with enough
    detail to self-correct on retry — found in evaluation that a bare KeyError
    ("'query'") produced confused, non-recovering behavior (see
    docs/EVALUATION_FAILURE_ANALYSIS.md, case #7) instead of a retried call."""


_SCHEMA_BY_NAME = {t["name"]: t["input_schema"] for t in TOOL_SCHEMAS}


def _validate_arguments(name: str, arguments: dict) -> None:
    schema = _SCHEMA_BY_NAME.get(name)
    if schema is None:
        return
    for field in schema.get("required", []):
        if not arguments.get(field):
            props = schema.get("properties", {})
            example = {f: f"<{props.get(f, {}).get('type', 'value')}>" for f in schema.get("required", [])}
            raise ToolArgumentError(
                f"Missing required argument '{field}' for tool '{name}'. "
                f"Retry this exact tool call with all required arguments, e.g. {name}({example})."
            )


def execute_tool(repository_id: int, name: str, arguments: dict) -> dict:
    _validate_arguments(name, arguments)
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
        if name == "analyze_impact":
            return _analyze_impact(session, repository_id, arguments["symbol_name"])
        if name == "co_changed_files":
            return _co_changed_files(session, repository_id, arguments["file_path"], arguments.get("limit", 8))
    finally:
        session.close()

    raise ValueError(f"Unknown tool: {name}")


def _analyze_impact(session, repository_id: int, symbol_name: str) -> dict:
    direct_callers = (
        session.query(Edge)
        .filter_by(repository_id=repository_id, relation="calls", target=symbol_name)
        .limit(30)
        .all()
    )
    direct_caller_names = {e.source for e in direct_callers}

    indirect_callers: set[str] = set()
    for caller_name in direct_caller_names:
        rows = (
            session.query(Edge)
            .filter_by(repository_id=repository_id, relation="calls", target=caller_name)
            .limit(30)
            .all()
        )
        indirect_callers.update(e.source for e in rows if e.source not in direct_caller_names)
    indirect_callers.discard(symbol_name)

    callees = (
        session.query(Edge)
        .filter_by(repository_id=repository_id, relation="calls", source=symbol_name)
        .limit(30)
        .all()
    )

    tests = (
        session.query(ChunkRecord)
        .filter(ChunkRecord.repository_id == repository_id)
        .filter(ChunkRecord.file_path.ilike("%test%"))
        .filter(ChunkRecord.content.ilike(f"%{symbol_name}%"))
        .limit(10)
        .all()
    )

    # Simple, explainable heuristic — not a claim of precise blast-radius modeling:
    # many direct callers and no tests is the riskiest combination to change blindly.
    if len(direct_caller_names) == 0:
        risk = "low"
    elif len(direct_caller_names) > 3 and not tests:
        risk = "high"
    elif len(direct_caller_names) > 0 and not tests:
        risk = "medium"
    else:
        risk = "medium" if len(direct_caller_names) > 5 else "low"

    return {
        "symbol": symbol_name,
        "direct_callers": [{"symbol": e.source, "file": e.source_file} for e in direct_callers],
        "indirect_callers": sorted(indirect_callers),
        "callees": [{"symbol": e.target} for e in callees],
        "tests_covering": [
            {"file": r.file_path, "symbol": r.symbol_name, "lines": f"{r.line_start}-{r.line_end}"} for r in tests
        ],
        "risk": risk,
        "risk_basis": (
            f"{len(direct_caller_names)} direct caller(s), "
            f"{len(indirect_callers)} indirect caller(s), "
            f"{len(tests)} test chunk(s) referencing this symbol"
        ),
    }


def _co_changed_files(session, repository_id: int, file_path: str, limit: int) -> dict:
    commits = (
        session.query(CommitRecord)
        .filter(CommitRecord.repository_id == repository_id)
        .filter(CommitRecord.files_changed.ilike(f"%{file_path}%"))
        .all()
    )
    counts: dict[str, int] = {}
    for c in commits:
        files = [f.strip() for f in (c.files_changed or "").splitlines() if f.strip()]
        if file_path not in files:
            continue  # substring match on the ILIKE above can over-match; confirm exact membership
        for f in files:
            if f != file_path:
                counts[f] = counts.get(f, 0) + 1
    ranked = sorted(counts.items(), key=lambda kv: kv[1], reverse=True)[:limit]
    return {
        "file": file_path,
        "commits_touching_file": len(commits),
        "co_changed_files": [{"file": f, "co_change_count": n} for f, n in ranked],
    }
