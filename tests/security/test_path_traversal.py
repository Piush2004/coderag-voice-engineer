"""Repositories are untrusted input (spec module 22/26/58). These tests fuzz
discover_files against traversal/escape attempts rather than trusting the
implementation is safe by inspection."""
import os

import pytest

from packages.rag.indexer import discover_files


def test_discovers_normal_files_within_root(tmp_path):
    (tmp_path / "a.py").write_text("x = 1")
    (tmp_path / "sub").mkdir()
    (tmp_path / "sub" / "b.py").write_text("y = 2")
    found = {p.name for p in discover_files(tmp_path)}
    assert found == {"a.py", "b.py"}


def test_ignores_dotgit_and_dependency_dirs(tmp_path):
    (tmp_path / ".git").mkdir()
    (tmp_path / ".git" / "config").write_text("junk")
    (tmp_path / "node_modules").mkdir()
    (tmp_path / "node_modules" / "pkg.js").write_text("junk")
    (tmp_path / "real.py").write_text("x = 1")
    found = {p.name for p in discover_files(tmp_path)}
    assert found == {"real.py"}


def test_skips_oversized_files(tmp_path):
    big = tmp_path / "big.py"
    big.write_text("x = 1\n" * 200_000)  # comfortably over MAX_FILE_BYTES
    small = tmp_path / "small.py"
    small.write_text("x = 1")
    found = {p.name for p in discover_files(tmp_path)}
    assert found == {"small.py"}


@pytest.mark.skipif(os.name == "nt", reason="symlink creation requires elevated privileges on Windows")
def test_symlink_escaping_root_is_excluded(tmp_path):
    outside = tmp_path.parent / "outside_secret.py"
    outside.write_text("SECRET = 1")
    root = tmp_path / "repo"
    root.mkdir()
    (root / "normal.py").write_text("x = 1")
    escape_link = root / "escape.py"
    escape_link.symlink_to(outside)
    try:
        found = {p.name for p in discover_files(root)}
        assert "escape.py" not in found
        assert "normal.py" in found
    finally:
        outside.unlink(missing_ok=True)


def test_does_not_index_its_own_data_directory(tmp_path, monkeypatch):
    import dataclasses

    from packages.rag import indexer as indexer_module
    from packages.shared.config import settings as real_settings

    data_dir = tmp_path / "data"
    data_dir.mkdir()
    (data_dir / "coderag.db").write_bytes(b"binary-ish sqlite content")
    # settings is a frozen dataclass; swap the module-level binding indexer.py reads
    # rather than mutating the (immutable) instance.
    fake_settings = dataclasses.replace(real_settings, chroma_path=str(data_dir / "chroma"))
    monkeypatch.setattr(indexer_module, "settings", fake_settings)

    repo_root = tmp_path  # data/ lives inside the "repository" being indexed
    (repo_root / "app.py").write_text("x = 1")
    found = {p.relative_to(repo_root) for p in discover_files(repo_root)}
    assert all("data" not in p.parts for p in found)
