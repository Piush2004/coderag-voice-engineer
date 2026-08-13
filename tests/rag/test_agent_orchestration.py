"""Deterministic tests for the orchestrator-level evidence-first enforcement added
after evaluation showed 8/11 benchmark failures were the model answering with zero
tool calls despite a system-prompt instruction not to (docs/EVALUATION_FAILURE_ANALYSIS.md).
Uses a scripted fake LLMProvider so this doesn't depend on live Ollama inference.
"""
from unittest.mock import patch

from packages.agents.state_machine import run_agent
from packages.rag.indexer import index_repository
from packages.rag.store import Conversation, get_session, init_db
from packages.shared.providers import LLMResponse, LLMToolCall


class _ScriptedLLM:
    """Returns each response in `responses` in order, one per .complete() call."""

    def __init__(self, responses: list[LLMResponse]):
        self._responses = list(responses)
        self.call_count = 0

    def complete(self, messages, system="", tools=None, max_tokens=1024):
        resp = self._responses[min(self.call_count, len(self._responses) - 1)]
        self.call_count += 1
        return resp


def _text_response(text: str) -> LLMResponse:
    return LLMResponse(text=text, tool_calls=[], stop_reason="stop")


def _tool_call_response(tool_name: str, arguments: dict) -> LLMResponse:
    call = LLMToolCall(id="call_1", name=tool_name, arguments=arguments)
    return LLMResponse(text="", tool_calls=[call], stop_reason="tool_calls", raw_content=[{"id": "call_1"}])


def _indexed_repo():
    import tempfile
    from pathlib import Path

    root = Path(tempfile.mkdtemp(prefix="agent_orch_test_"))
    (root / "auth.py").write_text("def login():\n    return True\n", encoding="utf-8")
    init_db()
    result = index_repository("orch-fixture", str(root))
    return result["repository_id"]


def _new_conversation(repository_id: int) -> int:
    session = get_session()
    try:
        conv = Conversation(repository_id=repository_id)
        session.add(conv)
        session.commit()
        session.refresh(conv)
        return conv.id
    finally:
        session.close()


def test_answer_without_any_tool_call_is_rejected_and_forces_retry():
    """Reproduces the dominant real failure mode: the model tries to answer
    immediately with no tool calls. The orchestrator must not accept that as final —
    it should inject a corrective message and force a real tool call."""
    repo_id = _indexed_repo()
    conv_id = _new_conversation(repo_id)

    scripted = _ScriptedLLM([
        _text_response("Login is typically handled by an auth middleware."),  # premature, must be rejected
        _tool_call_response("search_code", {"query": "login"}),
        _text_response("CONFIRMED: login() is defined in auth.py."),
    ])
    with patch("packages.agents.state_machine.get_llm_provider", return_value=scripted):
        result = run_agent(repo_id, conv_id, "How does login work?")

    assert scripted.call_count == 3  # the premature answer was NOT accepted at call 1
    assert result.status == "completed"
    assert "auth.py" in result.answer


def test_persistent_refusal_to_use_tools_eventually_gives_up_bounded():
    """If the model refuses to call a tool even after nudging, the orchestrator must
    not loop forever — it accepts the answer after MAX_FORCE_NUDGES rather than
    burning the entire iteration budget or hanging."""
    repo_id = _indexed_repo()
    conv_id = _new_conversation(repo_id)

    scripted = _ScriptedLLM([_text_response("I believe login works via standard auth.")])
    with patch("packages.agents.state_machine.get_llm_provider", return_value=scripted):
        result = run_agent(repo_id, conv_id, "How does login work?")

    # 1 initial attempt + 2 forced nudges = 3 calls, then it's accepted rather than
    # consuming the full max_agent_iterations budget.
    assert scripted.call_count == 3
    assert result.status == "completed"


def test_successful_tool_call_is_never_nudged():
    """A model that searches immediately should not be forced to search again."""
    repo_id = _indexed_repo()
    conv_id = _new_conversation(repo_id)

    scripted = _ScriptedLLM([
        _tool_call_response("search_code", {"query": "login"}),
        _text_response("CONFIRMED: login() is defined in auth.py."),
    ])
    with patch("packages.agents.state_machine.get_llm_provider", return_value=scripted):
        result = run_agent(repo_id, conv_id, "How does login work?")

    assert scripted.call_count == 2
    assert result.status == "completed"


def test_missing_required_tool_argument_gives_actionable_error():
    from packages.agents.tools import ToolArgumentError, execute_tool

    try:
        execute_tool(1, "search_code", {})  # missing required "query"
        assert False, "expected ToolArgumentError"
    except ToolArgumentError as e:
        assert "query" in str(e)
        assert "search_code" in str(e)
