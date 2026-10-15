"""Regression test for a real bug found during manual testing: indexing this
project's own root walked straight into demo-repos/*/ (each its own independently
git-initialized repository) and silently mixed unrelated content into the parent
repository's index — 30 of 272 chunks in a real run turned out to be from a nested
repo, not the repo actually being indexed. `.gitignore` doesn't help here since a
filesystem walk doesn't consult it; the fix is detecting nested `.git` roots
directly."""
from packages.rag.indexer import discover_files


def test_nested_git_repository_is_excluded_from_parent_indexing(tmp_path):
    import subprocess

    parent = tmp_path / "parent_repo"
    parent.mkdir()
    (parent / "app.py").write_text("x = 1\n", encoding="utf-8")

    nested = parent / "vendor" / "some-embedded-project"
    nested.mkdir(parents=True)
    (nested / "vendored.py").write_text("y = 2\n", encoding="utf-8")
    subprocess.run(["git", "init", "-q"], cwd=nested, check=True)
    subprocess.run(["git", "config", "user.email", "t@t"], cwd=nested, check=True)
    subprocess.run(["git", "config", "user.name", "t"], cwd=nested, check=True)
    subprocess.run(["git", "add", "-A"], cwd=nested, check=True)
    subprocess.run(["git", "commit", "-q", "-m", "init"], cwd=nested, check=True)

    found = {p.name for p in discover_files(parent)}
    assert found == {"app.py"}
    assert "vendored.py" not in found


def test_parents_own_dot_git_is_not_treated_as_nested(tmp_path):
    """The root repo's own .git must not cause every file to be excluded — only
    OTHER .git roots found under it."""
    import subprocess

    root = tmp_path / "repo"
    root.mkdir()
    (root / "app.py").write_text("x = 1\n", encoding="utf-8")
    subprocess.run(["git", "init", "-q"], cwd=root, check=True)
    subprocess.run(["git", "config", "user.email", "t@t"], cwd=root, check=True)
    subprocess.run(["git", "config", "user.name", "t"], cwd=root, check=True)
    subprocess.run(["git", "add", "-A"], cwd=root, check=True)
    subprocess.run(["git", "commit", "-q", "-m", "init"], cwd=root, check=True)

    found = {p.name for p in discover_files(root)}
    assert found == {"app.py"}
