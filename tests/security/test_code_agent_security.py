"""Regression tests for two real vulnerabilities found via an independent code-review
pass on packages/agents/code_agent.py and apps/backend/main.py:

1. investigate_and_propose read an LLM-supplied `FILE:` path with no containment
   check, so a response like `FILE: /etc/passwd` (or `../../etc/passwd`) let a
   *read-only* endpoint disclose arbitrary files the server process can read.
2. /api/v1/fixes/apply accepted patch text directly from the client with no link to
   an actual server-side proposal, so `authorized: true` gated nothing — a client
   could POST a hand-written diff and get it applied + auto-tested (an RCE
   primitive via crafted test-command side effects).

Both are fixed; these tests fail again if either regresses.
"""
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from apps.backend.main import app
from packages.agents.code_agent import get_proposal, investigate_and_propose, store_proposal
from packages.agents.state_machine import AgentResult
from packages.rag.store import Repository, get_session, init_db
from packages.shared.providers import LLMResponse


class _FakeLLM:
    def __init__(self, text: str):
        self._text = text

    def complete(self, *args, **kwargs):
        return LLMResponse(text=self._text, tool_calls=[], stop_reason="stop")


@pytest.fixture
def git_repo(tmp_path):
    import subprocess

    root = tmp_path / "repo"
    root.mkdir()
    (root / "app.py").write_text("x = 1\n", encoding="utf-8")
    subprocess.run(["git", "init", "-q"], cwd=root, check=True)
    subprocess.run(["git", "config", "user.email", "t@t"], cwd=root, check=True)
    subprocess.run(["git", "config", "user.name", "t"], cwd=root, check=True)
    subprocess.run(["git", "add", "-A"], cwd=root, check=True)
    subprocess.run(["git", "commit", "-q", "-m", "init"], cwd=root, check=True)

    init_db()
    session = get_session()
    try:
        repo = Repository(name="fixture", root_path=str(root.resolve()))
        session.add(repo)
        session.commit()
        session.refresh(repo)
        repo_id = repo.id
    finally:
        session.close()
    return repo_id, root


@pytest.mark.parametrize("malicious_path", ["../../../../etc/passwd", "/etc/passwd"])
def test_path_traversal_in_file_directive_is_rejected(git_repo, malicious_path):
    repo_id, root = git_repo
    outside_secret = root.parent / "secret_outside_repo.txt"
    outside_secret.write_text("TOP SECRET\n", encoding="utf-8")

    malicious_llm_response = f"FILE: {malicious_path}\n```\nleaked content\n```"
    with patch("packages.agents.code_agent.run_agent", return_value=AgentResult(answer="diag", citations=[])), \
         patch("packages.agents.code_agent.get_llm_provider", return_value=_FakeLLM(malicious_llm_response)):
        proposal = investigate_and_propose(repo_id, conversation_id=1, instruction="fix it")

    assert proposal.confident is False
    assert proposal.patch is None


def test_relative_path_within_repo_is_accepted(git_repo):
    repo_id, root = git_repo
    llm_response = "FILE: app.py\n```\nx = 2\n```"
    with patch("packages.agents.code_agent.run_agent", return_value=AgentResult(answer="diag", citations=[])), \
         patch("packages.agents.code_agent.get_llm_provider", return_value=_FakeLLM(llm_response)):
        proposal = investigate_and_propose(repo_id, conversation_id=1, instruction="fix it")

    assert proposal.confident is True
    assert "x = 2" in proposal.patch


def test_proposal_store_roundtrip():
    from packages.agents.code_agent import FixProposal

    p = FixProposal(diagnosis="d", citations=[], patch="patch text", confident=True, repository_id=42)
    proposal_id = store_proposal(p)
    fetched = get_proposal(proposal_id)
    assert fetched is p
    assert get_proposal("nonexistent-id") is None


def test_apply_endpoint_rejects_unknown_proposal_id():
    client = TestClient(app)
    resp = client.post(
        "/api/v1/fixes/apply",
        json={"repository_id": 1, "proposal_id": "does-not-exist", "authorized": True},
    )
    assert resp.status_code == 404


def test_apply_endpoint_rejects_proposal_for_a_different_repository():
    from packages.agents.code_agent import FixProposal

    proposal_id = store_proposal(
        FixProposal(diagnosis="d", citations=[], patch="x", confident=True, repository_id=999)
    )
    client = TestClient(app)
    resp = client.post(
        "/api/v1/fixes/apply",
        json={"repository_id": 1, "proposal_id": proposal_id, "authorized": True},
    )
    assert resp.status_code == 400


def test_apply_endpoint_requires_authorized_true():
    client = TestClient(app)
    resp = client.post(
        "/api/v1/fixes/apply",
        json={"repository_id": 1, "proposal_id": "irrelevant", "authorized": False},
    )
    assert resp.status_code == 400


def test_apply_endpoint_cannot_be_driven_by_client_supplied_patch_text():
    """The old (vulnerable) request shape included `patch` directly; the endpoint
    must reject it now that it requires `proposal_id` instead (missing required
    field -> 422, not silently accepted)."""
    client = TestClient(app)
    resp = client.post(
        "/api/v1/fixes/apply",
        json={
            "repository_id": 1,
            "diagnosis": "x",
            "citations": [],
            "patch": "--- a/x\n+++ b/x\n",
            "authorized": True,
        },
    )
    assert resp.status_code == 422
