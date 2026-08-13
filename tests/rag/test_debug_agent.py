"""Deterministic test for the dedicated debugging agent (spec Phase 11): verifies it
reuses the same bounded loop/evidence-first enforcement as the general agent (so all
of test_agent_orchestration.py's guarantees apply here too) but is wired to a
different, ranked-hypothesis system prompt via run_agent's new system_prompt param."""
from unittest.mock import patch

from packages.agents.state_machine import DEBUG_SYSTEM_PROMPT, SYSTEM_PROMPT, run_debug_agent
from packages.rag.indexer import index_repository
from packages.rag.store import Conversation, get_session, init_db
from packages.shared.providers import LLMResponse, LLMToolCall


class _CapturingLLM:
    """Records the system prompt each call was made with, then answers plainly."""

    def __init__(self):
        self.system_prompts_seen = []

    def complete(self, messages, system="", tools=None, max_tokens=1024):
        self.system_prompts_seen.append(system)
        if len(self.system_prompts_seen) == 1:
            call = LLMToolCall(id="c1", name="search_code", arguments={"query": "error"})
            return LLMResponse(text="", tool_calls=[call], stop_reason="tool_calls", raw_content=[{"id": "c1"}])
        return LLMResponse(
            text="HYPOTHESIS: most likely a null check is missing.", tool_calls=[], stop_reason="stop"
        )


def _indexed_repo():
    import tempfile
    from pathlib import Path

    root = Path(tempfile.mkdtemp(prefix="debug_agent_test_"))
    (root / "app.py").write_text("def handler():\n    return None.value\n", encoding="utf-8")
    init_db()
    return index_repository("debug-fixture", str(root))["repository_id"]


def test_debug_agent_uses_the_debug_specific_system_prompt():
    repo_id = _indexed_repo()
    session = get_session()
    conv = Conversation(repository_id=repo_id)
    session.add(conv)
    session.commit()
    session.refresh(conv)
    session.close()

    llm = _CapturingLLM()
    with patch("packages.agents.state_machine.get_llm_provider", return_value=llm):
        result = run_debug_agent(repo_id, conv.id, "handler() raises AttributeError: 'NoneType' has no 'value'")

    assert all(sp == DEBUG_SYSTEM_PROMPT for sp in llm.system_prompts_seen)
    assert all(sp != SYSTEM_PROMPT for sp in llm.system_prompts_seen)
    assert "HYPOTHESIS" in result.answer
    assert DEBUG_SYSTEM_PROMPT != SYSTEM_PROMPT  # sanity: prompts are genuinely different
