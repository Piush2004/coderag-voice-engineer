from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class Symbol:
    name: str
    kind: str  # "function" | "class" | "method"
    file_path: str
    line_start: int
    line_end: int
    source: str
    parent: str | None = None  # enclosing class/module symbol name
    docstring: str | None = None
    calls: list[str] = field(default_factory=list)  # callee names referenced in body


@dataclass
class FileAnalysis:
    file_path: str
    language: str
    imports: list[str]
    symbols: list[Symbol]
    line_count: int
