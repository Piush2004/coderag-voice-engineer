"""Code-aware chunking: chunks are symbols (function/method/class) or, for a file
with no extracted symbols, the whole file — never arbitrary token windows
(spec module 17)."""
from __future__ import annotations

from dataclasses import dataclass

from packages.code_intelligence.symbols import FileAnalysis


@dataclass
class Chunk:
    id: str
    repository_id: int
    file_path: str
    language: str | None
    chunk_type: str
    symbol_name: str | None
    parent_symbol: str | None
    line_start: int
    line_end: int
    content: str


def chunk_file(repository_id: int, analysis: FileAnalysis, source: str) -> list[Chunk]:
    chunks: list[Chunk] = []
    # Skip nested methods as separate chunks when their enclosing class is small
    # enough to be one coherent unit; otherwise every function/class is its own chunk.
    top_level = [s for s in analysis.symbols if s.kind in ("function", "class")]
    for sym in top_level:
        header = f"# {analysis.file_path} :: {sym.kind} {sym.name} (lines {sym.line_start}-{sym.line_end})\n"
        content = header + sym.source
        chunks.append(
            Chunk(
                id=f"{repository_id}:{analysis.file_path}:{sym.name}:{sym.line_start}-{sym.line_end}",
                repository_id=repository_id,
                file_path=analysis.file_path,
                language=analysis.language,
                chunk_type=sym.kind,
                symbol_name=sym.name,
                parent_symbol=sym.parent,
                line_start=sym.line_start,
                line_end=sym.line_end,
                content=content,
            )
        )
    # Methods get their own chunk too (finer retrieval granularity), tagged with parent.
    for sym in analysis.symbols:
        if sym.kind == "method":
            header = (
                f"# {analysis.file_path} :: {sym.parent}.{sym.name} "
                f"(lines {sym.line_start}-{sym.line_end})\n"
            )
            chunks.append(
                Chunk(
                    id=f"{repository_id}:{analysis.file_path}:{sym.parent}.{sym.name}:{sym.line_start}-{sym.line_end}",
                    repository_id=repository_id,
                    file_path=analysis.file_path,
                    language=analysis.language,
                    chunk_type="method",
                    symbol_name=sym.name,
                    parent_symbol=sym.parent,
                    line_start=sym.line_start,
                    line_end=sym.line_end,
                    content=header + sym.source,
                )
            )
    if not chunks:
        # Fallback: whole-file chunk (config, docs, unsupported languages).
        lines = source.count("\n") + 1
        chunks.append(
            Chunk(
                id=f"{repository_id}:{analysis.file_path}:module:1-{lines}",
                repository_id=repository_id,
                file_path=analysis.file_path,
                language=analysis.language,
                chunk_type="module",
                symbol_name=None,
                parent_symbol=None,
                line_start=1,
                line_end=lines,
                content=f"# {analysis.file_path}\n" + source,
            )
        )
    return chunks
