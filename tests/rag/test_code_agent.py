"""Deterministic tests for the code-modification agent's WRITE+EXECUTE path
(packages/agents/code_agent.py::apply_fix). Bypasses the LLM (constructs FixProposal
directly) so this is fast and reproducible — the live-LLM propose step is covered
separately by evaluation/agent_eval.py (real Ollama inference, not suitable for the
fast test suite). This locks in the real, observed behavior from manual testing: a
correct patch applies and tests pass; an incomplete/wrong patch applies but the
sandboxed test run catches it — the system never reports false success.
"""
import shutil
import subprocess
from pathlib import Path

import pytest

from packages.agents.code_agent import FixProposal, apply_fix
from packages.rag.store import Repository, get_session, init_db

PRICING_SRC = '''"""Order pricing logic."""


class Order:
    def __init__(self, items):
        self.items = items

    def subtotal(self):
        return sum(price * qty for price, qty in self.items)


def apply_discount(subtotal, discount_percent):
    """BUG: divides by 100 twice."""
    discount_percent = discount_percent / 100
    return subtotal - (subtotal * discount_percent / 100)


def calculate_total(order, discount_percent=0):
    subtotal = order.subtotal()
    if discount_percent:
        return apply_discount(subtotal, discount_percent)
    return subtotal
'''

TEST_SRC = """from app.pricing import Order, apply_discount, calculate_total


def test_apply_discount_10_percent_off_100_is_90():
    assert apply_discount(100, 10) == 90


def test_calculate_total_with_discount():
    order = Order([(50, 2)])
    assert calculate_total(order, 10) == 90
"""


@pytest.fixture
def git_repo_with_bug(tmp_path):
    root = tmp_path / "pricing_repo"
    (root / "app").mkdir(parents=True)
    (root / "tests").mkdir()
    (root / "app" / "__init__.py").write_text("")
    (root / "app" / "pricing.py").write_text(PRICING_SRC, encoding="utf-8")
    (root / "tests" / "test_pricing.py").write_text(TEST_SRC, encoding="utf-8")

    def git(*args):
        subprocess.run(["git", *args], cwd=root, check=True, capture_output=True, text=True)

    git("init", "-q")
    git("config", "user.email", "test@local")
    git("config", "user.name", "Test")
    git("add", "-A")
    git("commit", "-q", "-m", "initial")

    init_db()
    session = get_session()
    try:
        repo = Repository(name="pricing-fixture", root_path=str(root.resolve()))
        session.add(repo)
        session.commit()
        session.refresh(repo)
        repo_id = repo.id
    finally:
        session.close()

    yield repo_id, root
    shutil.rmtree(tmp_path, ignore_errors=True)


def _diff_for(root: Path, new_content: str) -> str:
    import difflib

    old = (root / "app" / "pricing.py").read_text(encoding="utf-8")
    return "".join(
        difflib.unified_diff(
            old.splitlines(keepends=True), new_content.splitlines(keepends=True),
            fromfile="a/app/pricing.py", tofile="b/app/pricing.py",
        )
    )


def test_correct_patch_applies_and_tests_pass(git_repo_with_bug):
    repo_id, root = git_repo_with_bug
    fixed = PRICING_SRC.replace(
        '    discount_percent = discount_percent / 100\n    return subtotal - (subtotal * discount_percent / 100)',
        "    return subtotal - (subtotal * discount_percent / 100)",
    )
    proposal = FixProposal(diagnosis="test", citations=[], patch=_diff_for(root, fixed), confident=True)

    result = apply_fix(repo_id, proposal, run_test_command=["python", "-m", "pytest", "-q"])

    assert result.applied is True
    assert result.tests_passed is True, result.test_output
    assert result.worktree_path and Path(result.worktree_path).exists()
    # the real working tree must be untouched
    assert "divides by 100 twice" in (root / "app" / "pricing.py").read_text(encoding="utf-8")


def test_incomplete_patch_applies_but_tests_correctly_fail(git_repo_with_bug):
    """Reproduces real observed behavior: a small local model sometimes returns a
    truncated file (drops unrelated classes/functions). The patch still applies
    (it's syntactically a valid diff), but the safety net — running real tests in
    the sandbox — must catch the regression rather than the system claiming success."""
    repo_id, root = git_repo_with_bug
    truncated = (
        '"""Order pricing logic."""\n\n\n'
        "def apply_discount(subtotal, discount_percent):\n"
        "    return subtotal - (subtotal * discount_percent / 100)\n"
    )
    proposal = FixProposal(diagnosis="test", citations=[], patch=_diff_for(root, truncated), confident=True)

    result = apply_fix(repo_id, proposal, run_test_command=["python", "-m", "pytest", "-q"])

    assert result.applied is True
    assert result.tests_passed is False
    assert "ImportError" in result.test_output or "cannot import name" in result.test_output


def test_apply_fix_requires_a_confident_proposal(git_repo_with_bug):
    repo_id, _ = git_repo_with_bug
    proposal = FixProposal(diagnosis="couldn't find it", citations=[], patch=None, confident=False)
    result = apply_fix(repo_id, proposal)
    assert result.applied is False
    assert "No confident patch" in result.error


def test_apply_fix_rejects_non_git_repository(tmp_path):
    init_db()
    session = get_session()
    try:
        repo = Repository(name="not-git", root_path=str(tmp_path.resolve()))
        session.add(repo)
        session.commit()
        session.refresh(repo)
        repo_id = repo.id
    finally:
        session.close()
    proposal = FixProposal(diagnosis="x", citations=[], patch="--- a\n+++ b\n", confident=True)
    result = apply_fix(repo_id, proposal)
    assert result.applied is False
    assert "not a git repo" in result.error
