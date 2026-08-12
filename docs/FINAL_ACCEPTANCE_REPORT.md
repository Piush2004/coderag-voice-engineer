# Final Acceptance Report

This report is a snapshot, not a permanent claim — it reflects the state as of the
timestamp below. [PROJECT_STATUS.md](PROJECT_STATUS.md) is the continuously-updated
source of truth; this file summarizes it for a portfolio/interview reader.

**Snapshot date: 2026-08-13.**

## What this project is

A voice-first AI software-engineering platform: code-aware RAG (tree-sitter parsing,
hybrid semantic+lexical retrieval, code graph, Git intelligence) plus a bounded
tool-calling agent that answers evidence-grounded questions about a real repository,
with a code-modification agent (investigate → propose → authorize → isolated patch →
test → verify) built on top. Runs fully locally via Ollama, no API key required; also
supports Anthropic/OpenAI as swap-in providers.

## Architecture

See [ARCHITECTURE.md](ARCHITECTURE.md) for diagrams. Key design decisions and why
each was made (including the ones forced by this environment's real constraints — no
Docker, no Postgres, no cloud API keys) are in [DECISIONS.md](DECISIONS.md) and
[INITIAL_AUDIT.md](INITIAL_AUDIT.md).

## Verified capabilities (DONE, with evidence)

| Capability | Evidence |
|---|---|
| Code-aware parsing (Python/JS/TS/Go) | 6 parser tests, `tests/unit/test_parser.py` |
| Code-aware chunking | 2 tests, `tests/unit/test_chunker.py` |
| Repository ingestion (path-safe, secret-redacted) | 6 path-traversal tests + 7 redaction tests, `tests/security/` |
| Hybrid retrieval | Recall@5=1.00, MRR=1.00 on fixture; correct top-1 across 3 independent demo repos in 3 languages |
| Full agent loop, live, local, no API key | Verified via curl and live browser UI against real repos, correct citations |
| Code modification agent | 4 deterministic tests, `tests/rag/test_code_agent.py`; one live end-to-end run against a real bug, correctly reported test failure rather than false success |
| Concurrency safety | Real bug found (Chroma client race) and fixed with a regression test |
| Voice (browser) | Verified live in-browser: mic, transcript, spoken answer, stop |

Full test suite: 26 passed, 1 skipped (Windows symlink privilege requirement) as of
this snapshot.

## Honest limitations

- Local model (`qwen2.5:3b-instruct`) sometimes answers UNKNOWN without searching
  first, despite an explicit system-prompt instruction not to — a real
  instruction-following gap of a 3B CPU model, documented with real numbers in
  [PROJECT_STATUS.md](PROJECT_STATUS.md), not smoothed over.
- Code-modification agent's patch generation is unreliable for whole-file accuracy
  (observed: dropped unrelated code in one live test) — mitigated, not solved, by
  running real tests before ever reporting success.
- No auth/multi-tenancy, no rate limiting, no Docker, no CI, no deployment. See
  [SECURITY.md](SECURITY.md) and [DEPLOYMENT.md](DEPLOYMENT.md) for the complete,
  explicit list of what's not done and why.
- Test/impact-analysis/debugging as *dedicated* agent workflows don't exist yet — the
  general agent and the code-modification agent's investigation step cover much of
  this ad hoc, but there's no specialized prompt/flow for each.

## Recommendation

This is a real, working local-first prototype with genuine test coverage and honest
documentation of its limits — a reasonable base for a portfolio demo emphasizing
"how do you build a trustworthy agent system," specifically the evidence-first
answering and the test-verification safety net on code changes. It is **not**
production-deployed and should not be described as such. Next highest-leverage steps
are listed in [PROJECT_STATUS.md](PROJECT_STATUS.md)'s "Recommended next slice."
