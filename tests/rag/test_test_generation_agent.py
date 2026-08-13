"""Deterministic tests for the test-generation agent (spec Phase 13). Verifies:
1. it can create a brand-new test file (not just edit an existing one) — the
   underlying _propose_file_change was extended to support this since the old
   investigate_and_propose rejected any target file that didn't already exist.
2. the generated test proposal goes through the exact same apply_fix path (real
   sandboxed test execution) as a bug fix — never claims a test passes without
   actually running it.
"""
import subprocess
from unittest.mock import patch

import pytest

from packages.agents.code_agent import apply_fix, generate_tests
from packages.agents.state_machine import AgentResult
from packages.rag.store import Repository, get_session, init_db
from packages.shared.providers import LLMResponse


class _FakeLLM:
    def __init__(self, text: str):
        self._text = text

    def complete(self, *args, **kwargs):
        return LLMResponse(text=self._text, tool_calls=[], stop_reason="stop")


@pytest.fixture
def git_repo_no_tests(tmp_path):
    root = tmp_path / "repo"
    (root / "app").mkdir(parents=True)
    (root / "app" / "__init__.py").write_text("", encoding="utf-8")
    (root / "app" / "math_utils.py").write_text(
        "def add(a, b):\n    return a + b\n", encoding="utf-8"
    )
    subprocess.run(["git", "init", "-q"], cwd=root, check=True)
    subprocess.run(["git", "config", "user.email", "t@t"], cwd=root, check=True)
    subprocess.run(["git", "config", "user.name", "t"], cwd=root, check=True)
    subprocess.run(["git", "add", "-A"], cwd=root, check=True)
    subprocess.run(["git", "commit", "-q", "-m", "init"], cwd=root, check=True)

    init_db()
    session = get_session()
    try:
        repo = Repository(name="testgen-fixture", root_path=str(root.resolve()))
        session.add(repo)
        session.commit()
        session.refresh(repo)
        repo_id = repo.id
    finally:
        session.close()
    return repo_id, root


def test_generate_tests_can_create_a_brand_new_test_file(git_repo_no_tests):
    repo_id, root = git_repo_no_tests
    llm_response = (
        "FILE: tests/test_math_utils.py\n```\n"
        "from app.math_utils import add\n\n\n"
        "def test_add():\n    assert add(2, 3) == 5\n"
        "```"
    )
    with patch("packages.agents.code_agent.run_agent", return_value=AgentResult(answer="diag", citations=[])), \
         patch("packages.agents.code_agent.get_llm_provider", return_value=_FakeLLM(llm_response)):
        proposal = generate_tests(repo_id, conversation_id=1, target_description="app/math_utils.py add()")

    assert proposal.confident is True
    assert "/dev/null" in proposal.patch  # new-file diff marker
    assert "test_add" in proposal.patch


def test_generated_test_actually_runs_and_passes(git_repo_no_tests):
    repo_id, root = git_repo_no_tests
    llm_response = (
        "FILE: tests/test_math_utils.py\n```\n"
        "from app.math_utils import add\n\n\n"
        "def test_add():\n    assert add(2, 3) == 5\n"
        "```"
    )
    with patch("packages.agents.code_agent.run_agent", return_value=AgentResult(answer="diag", citations=[])), \
         patch("packages.agents.code_agent.get_llm_provider", return_value=_FakeLLM(llm_response)):
        proposal = generate_tests(repo_id, conversation_id=1, target_description="app/math_utils.py add()")

    result = apply_fix(repo_id, proposal, run_test_command=["python", "-m", "pytest", "-q"])

    assert result.applied is True
    assert result.tests_passed is True, result.test_output
    # the real working tree must be untouched — no test file created there
    assert not (root / "tests").exists()
