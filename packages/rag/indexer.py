"""Repository ingestion pipeline: discovery -> parse -> chunk -> embed -> graph -> git.

Security validation: refuses to index outside the given root, skips binary files,
skips anything over a size cap, and never follows symlinks out of the tree.
"""
from __future__ import annotations

import hashlib
import logging
import subprocess
from datetime import datetime
from pathlib import Path

logger = logging.getLogger(__name__)

from packages.code_intelligence.parser import detect_language, get_parser
from packages.code_intelligence.symbols import FileAnalysis
from packages.rag.chunker import chunk_file
from packages.rag.store import (
    ChunkRecord,
    CommitRecord,
    Edge,
    FileRecord,
    Repository,
    SymbolRecord,
    get_chroma_collection,
    get_session,
)
from packages.shared.config import settings
from packages.shared.providers import get_embedding_provider

MAX_FILE_BYTES = 512_000
IGNORED_DIRS = {
    ".git", "node_modules", "__pycache__", ".venv", "venv", "dist", "build",
    ".next", ".mypy_cache", ".pytest_cache", "coverage", ".turbo",
}


def discover_files(root: Path) -> list[Path]:
    root = root.resolve()
    data_dir = Path(settings.chroma_path).resolve().parent
    files = []
    for p in root.rglob("*"):
        if not p.is_file():
            continue
        if any(part in IGNORED_DIRS for part in p.parts):
            continue
        resolved = p.resolve()
        try:
            resolved.relative_to(root)  # raises if symlink escapes root
        except ValueError:
            continue
        try:
            resolved.relative_to(data_dir)
            continue  # inside our own data dir — never index our own indexes
        except ValueError:
            pass  # not inside data dir, proceed normally
        if p.stat().st_size > MAX_FILE_BYTES:
            continue
        files.append(p)
    return files


def index_repository(name: str, root_path: str, progress_cb=None) -> dict:
    root = Path(root_path)
    if not root.exists() or not root.is_dir():
        raise ValueError(f"Repository path does not exist or is not a directory: {root_path}")
    root = root.resolve()

    session = get_session()
    try:
        repo = session.query(Repository).filter_by(root_path=str(root.resolve())).first()
        if repo is None:
            repo = Repository(name=name, root_path=str(root.resolve()))
            session.add(repo)
            session.commit()
            session.refresh(repo)
        else:
            # Idempotent re-index: clear previous derived data for this repo.
            session.query(ChunkRecord).filter_by(repository_id=repo.id).delete()
            session.query(SymbolRecord).filter_by(repository_id=repo.id).delete()
            session.query(FileRecord).filter_by(repository_id=repo.id).delete()
            session.query(Edge).filter_by(repository_id=repo.id).delete()
            session.query(CommitRecord).filter_by(repository_id=repo.id).delete()
            session.commit()

        files = discover_files(root)
        embedder = get_embedding_provider(settings.embedding_provider)
        collection = get_chroma_collection()
        try:
            collection.delete(where={"repository_id": repo.id})
        except Exception:
            pass

        all_chunks = []
        symbol_names_by_file: dict[str, list[str]] = {}
        parsed_count = 0
        for i, path in enumerate(files):
            rel = str(path.relative_to(root)).replace("\\", "/")
            language = detect_language(rel)
            try:
                source = path.read_text(encoding="utf-8")
            except (UnicodeDecodeError, OSError):
                continue  # binary or unreadable — skip

            content_hash = hashlib.sha256(source.encode("utf-8")).hexdigest()
            file_record = FileRecord(
                repository_id=repo.id,
                path=rel,
                language=language,
                line_count=source.count("\n") + 1,
                content_hash=content_hash,
            )
            session.add(file_record)
            session.flush()

            if language:
                try:
                    parser = get_parser(language)
                    analysis: FileAnalysis = parser.analyze(rel, source)
                    parsed_count += 1
                except Exception as e:  # noqa: BLE001 — one bad file must not abort indexing
                    logger.warning("Parse failed for %s (%s): %s", rel, language, e)
                    analysis = FileAnalysis(rel, language, [], [], source.count("\n") + 1)
            else:
                analysis = FileAnalysis(rel, "text", [], [], source.count("\n") + 1)

            for sym in analysis.symbols:
                session.add(
                    SymbolRecord(
                        file_id=file_record.id,
                        repository_id=repo.id,
                        name=sym.name,
                        kind=sym.kind,
                        parent=sym.parent,
                        line_start=sym.line_start,
                        line_end=sym.line_end,
                        docstring=sym.docstring,
                    )
                )
                symbol_names_by_file.setdefault(rel, []).append(sym.name)
                for callee in sym.calls:
                    session.add(
                        Edge(
                            repository_id=repo.id,
                            relation="calls",
                            source=sym.name,
                            target=callee,
                            source_file=rel,
                        )
                    )
            for imp in analysis.imports:
                session.add(
                    Edge(
                        repository_id=repo.id,
                        relation="imports",
                        source=rel,
                        target=imp,
                        source_file=rel,
                    )
                )

            chunks = chunk_file(repo.id, analysis, source)
            all_chunks.extend(chunks)
            if progress_cb:
                progress_cb(i + 1, len(files))

        session.commit()

        # Batch embed + upsert into vector store.
        BATCH = 64
        for start in range(0, len(all_chunks), BATCH):
            batch = all_chunks[start : start + BATCH]
            vectors = embedder.embed([c.content for c in batch])
            collection.upsert(
                ids=[c.id for c in batch],
                embeddings=vectors,
                documents=[c.content for c in batch],
                metadatas=[
                    {
                        "repository_id": repo.id,
                        "file_path": c.file_path,
                        "language": c.language or "",
                        "chunk_type": c.chunk_type,
                        "symbol_name": c.symbol_name or "",
                        "parent_symbol": c.parent_symbol or "",
                        "line_start": c.line_start,
                        "line_end": c.line_end,
                    }
                    for c in batch
                ],
            )
            for c in batch:
                session.add(
                    ChunkRecord(
                        id=c.id,
                        repository_id=repo.id,
                        file_path=c.file_path,
                        language=c.language,
                        chunk_type=c.chunk_type,
                        symbol_name=c.symbol_name,
                        parent_symbol=c.parent_symbol,
                        line_start=c.line_start,
                        line_end=c.line_end,
                        content=c.content,
                    )
                )
        session.commit()

        commit_count = _index_git_history(session, repo, root)

        return {
            "repository_id": repo.id,
            "files_indexed": len(files),
            "files_parsed": parsed_count,
            "chunks_indexed": len(all_chunks),
            "commits_indexed": commit_count,
        }
    finally:
        session.close()


def _index_git_history(session, repo: Repository, root: Path, limit: int = 200) -> int:
    if not (root / ".git").exists():
        return 0
    try:
        out = subprocess.run(
            ["git", "log", f"-{limit}", "--name-only", "--pretty=format:%H|%an|%ad|%s", "--date=iso"],
            cwd=root, capture_output=True, text=True, timeout=30, check=True,
        ).stdout
    except (subprocess.CalledProcessError, FileNotFoundError, subprocess.TimeoutExpired):
        return 0

    count = 0
    for block in out.split("\n\n"):
        lines = [line for line in block.splitlines() if line.strip()]
        if not lines:
            continue
        header, *changed_files = lines
        parts = header.split("|", 3)
        if len(parts) != 4:
            continue
        sha, author, date_str, message = parts
        try:
            committed_at = datetime.fromisoformat(date_str.strip())
        except ValueError:
            committed_at = None
        session.add(
            CommitRecord(
                repository_id=repo.id,
                sha=sha,
                author=author,
                message=message,
                committed_at=committed_at,
                files_changed="\n".join(changed_files),
            )
        )
        count += 1
    session.commit()
    return count
