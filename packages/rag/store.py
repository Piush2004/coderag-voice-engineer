"""Relational schema (SQLite for local dev; same models target Postgres in prod —
see docs/DECISIONS.md) plus the embedded Chroma vector store wrapper."""
from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import (
    Column,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
    create_engine,
)
from sqlalchemy.orm import DeclarativeBase, Session, relationship, sessionmaker

from packages.shared.config import settings


class Base(DeclarativeBase):
    pass


def _now() -> datetime:
    return datetime.now(timezone.utc)


class Repository(Base):
    __tablename__ = "repositories"
    id = Column(Integer, primary_key=True)
    name = Column(String, nullable=False)
    root_path = Column(String, nullable=False, unique=True)
    default_branch = Column(String, default="main")
    created_at = Column(DateTime, default=_now)

    files = relationship("FileRecord", back_populates="repository", cascade="all, delete-orphan")


class FileRecord(Base):
    __tablename__ = "files"
    id = Column(Integer, primary_key=True)
    repository_id = Column(Integer, ForeignKey("repositories.id"), nullable=False)
    path = Column(String, nullable=False)
    language = Column(String, nullable=True)
    line_count = Column(Integer, default=0)
    content_hash = Column(String, nullable=True)
    updated_at = Column(DateTime, default=_now, onupdate=_now)

    repository = relationship("Repository", back_populates="files")
    symbols = relationship("SymbolRecord", back_populates="file", cascade="all, delete-orphan")

    __table_args__ = (UniqueConstraint("repository_id", "path", name="uq_file_repo_path"),)


class SymbolRecord(Base):
    __tablename__ = "symbols"
    id = Column(Integer, primary_key=True)
    file_id = Column(Integer, ForeignKey("files.id"), nullable=False)
    repository_id = Column(Integer, ForeignKey("repositories.id"), nullable=False)
    name = Column(String, nullable=False)
    kind = Column(String, nullable=False)
    parent = Column(String, nullable=True)
    line_start = Column(Integer, nullable=False)
    line_end = Column(Integer, nullable=False)
    docstring = Column(Text, nullable=True)

    file = relationship("FileRecord", back_populates="symbols")


class ChunkRecord(Base):
    """One retrievable unit. Mirrors the vector-store entry (same id)."""

    __tablename__ = "chunks"
    id = Column(String, primary_key=True)  # "{repo_id}:{path}:{symbol|module}:{start}-{end}"
    repository_id = Column(Integer, ForeignKey("repositories.id"), nullable=False)
    file_path = Column(String, nullable=False)
    language = Column(String, nullable=True)
    chunk_type = Column(String, nullable=False)  # module|class|function|method
    symbol_name = Column(String, nullable=True)
    parent_symbol = Column(String, nullable=True)
    line_start = Column(Integer, nullable=False)
    line_end = Column(Integer, nullable=False)
    content = Column(Text, nullable=False)


class Edge(Base):
    """Code graph edge: e.g. ('calls', caller_symbol, callee_symbol)."""

    __tablename__ = "edges"
    id = Column(Integer, primary_key=True)
    repository_id = Column(Integer, ForeignKey("repositories.id"), nullable=False)
    relation = Column(String, nullable=False)  # calls|imports|inherits|tests
    source = Column(String, nullable=False)  # symbol or file identifier
    target = Column(String, nullable=False)
    source_file = Column(String, nullable=True)
    target_file = Column(String, nullable=True)


class CommitRecord(Base):
    __tablename__ = "commits"
    id = Column(Integer, primary_key=True)
    repository_id = Column(Integer, ForeignKey("repositories.id"), nullable=False)
    sha = Column(String, nullable=False)
    author = Column(String, nullable=True)
    message = Column(Text, nullable=True)
    committed_at = Column(DateTime, nullable=True)
    files_changed = Column(Text, nullable=True)  # newline-joined paths

    __table_args__ = (UniqueConstraint("repository_id", "sha", name="uq_commit_repo_sha"),)


class Conversation(Base):
    __tablename__ = "conversations"
    id = Column(Integer, primary_key=True)
    repository_id = Column(Integer, ForeignKey("repositories.id"), nullable=True)
    created_at = Column(DateTime, default=_now)


class Message(Base):
    __tablename__ = "messages"
    id = Column(Integer, primary_key=True)
    conversation_id = Column(Integer, ForeignKey("conversations.id"), nullable=False)
    role = Column(String, nullable=False)
    content = Column(Text, nullable=False)
    created_at = Column(DateTime, default=_now)


class AgentRun(Base):
    __tablename__ = "agent_runs"
    id = Column(Integer, primary_key=True)
    conversation_id = Column(Integer, ForeignKey("conversations.id"), nullable=False)
    task_type = Column(String, nullable=True)
    status = Column(String, default="running")
    iterations = Column(Integer, default=0)
    started_at = Column(DateTime, default=_now)
    finished_at = Column(DateTime, nullable=True)


class ToolCallRecord(Base):
    __tablename__ = "tool_calls"
    id = Column(Integer, primary_key=True)
    agent_run_id = Column(Integer, ForeignKey("agent_runs.id"), nullable=False)
    tool_name = Column(String, nullable=False)
    arguments = Column(Text, nullable=True)
    result_summary = Column(Text, nullable=True)
    created_at = Column(DateTime, default=_now)


_engine = create_engine(f"sqlite:///{settings.sqlite_path}", future=True)
SessionLocal = sessionmaker(bind=_engine, expire_on_commit=False, future=True)


def init_db() -> None:
    Base.metadata.create_all(_engine)


def get_session() -> Session:
    return SessionLocal()


import threading

_chroma_client = None
_chroma_collection = None
_chroma_lock = threading.Lock()


def get_chroma_collection():
    """Lazy singleton, guarded by a lock: FastAPI runs sync endpoints in a
    threadpool, and concurrent unguarded calls here raced to construct two
    chromadb.PersistentClient instances against the same path, which crashes
    chromadb's Rust bindings (AttributeError: 'RustBindingsAPI' object has no
    attribute 'bindings') — reproduced when a reindex request landed while the
    process was still cold. See tests/rag/test_concurrent_chroma_init.py."""
    global _chroma_client, _chroma_collection
    if _chroma_collection is None:
        with _chroma_lock:
            if _chroma_collection is None:
                import chromadb

                _chroma_client = chromadb.PersistentClient(path=settings.chroma_path)
                _chroma_collection = _chroma_client.get_or_create_collection(
                    name="code_chunks", metadata={"hnsw:space": "cosine"}
                )
    return _chroma_collection
