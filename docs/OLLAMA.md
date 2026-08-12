# Local LLM via Ollama

## Why

The reference deployment target is Anthropic/OpenAI, but requiring a paid API key
would make this project untestable without credentials. Ollama is the default
development provider precisely so the agent loop is fully testable locally with zero
external cost or network dependency (spec module 45).

## What's installed / used in this environment

- Ollama server: `C:\Users\piush\AppData\Local\Programs\Ollama\ollama.exe`, v0.32.6.
  Not running by default on this machine — start with `ollama serve`.
- Model: **`qwen2.5:3b-instruct`** (1.9GB, 32K context, `tools` capability).

### How the model was chosen

`nemotron-mini:latest` (already pulled, 4.2B, advertises `tools` capability) was
tried first and **rejected**: it returned empty content with no `tool_calls` on a
direct function-calling test, i.e. it does not reliably call tools despite the
capability flag. `qwen2.5:3b-instruct` was pulled next (1.9GB — small, fast to
verify) and passes real tool-call tests: correct `tool_calls` output for both
numeric and string-typed arguments, 32K context (vs. nemotron-mini's 4096, which
would be too small for tool-result round-trips anyway).

License note: Qwen2.5 ships under Alibaba's Qwen Research License — fine for local
development/evaluation use as done here; re-check the license before any commercial
redistribution of the weights.

Change the model without touching code via `.env`:
```
OLLAMA_BASE_URL=http://localhost:11434
OLLAMA_MODEL=qwen2.5:3b-instruct
```

## Health check

`GET /api/v1/health/llm` — checks server reachability, model presence, and (with a
real ping) model responsiveness/latency, so the UI/CLI can tell a user Ollama is down
*before* they send a chat message, not after
(`packages/shared/providers.py::OllamaProvider.health_check`).

## Honest limitations of this model, measured

This is a **3B-parameter model running on CPU**, not a frontier coding model. Real,
measured behavior from `evaluation/adhoc_probe.py` and `evaluation/agent_eval.py`
against this repository (see [PROJECT_STATUS.md](PROJECT_STATUS.md) for the full
table):

- When it does call tools, tool selection and argument construction are reliable and
  results are correctly cited (file:line) — verified against ground truth.
- It sometimes answers "UNKNOWN" **without calling a tool first**, despite an explicit
  system-prompt instruction requiring at least one tool call before answering. This is
  a real instruction-following gap of a 3B model, not a bug in the orchestrator (the
  orchestrator's loop-protection and tool execution are independently verified via
  direct tool tests in `tests/`).
- CPU inference is slow: multi-tool-call turns can take 20–90+ seconds. The agent
  timeout (`CODERAG_AGENT_TIMEOUT`) defaults to 180s locally to accommodate this
  rather than truncating legitimate work.
- A larger local model (e.g. `qwen2.5-coder:7b` or `qwen2.5:7b-instruct`, if the
  machine has the RAM/VRAM) would likely improve both tool-use consistency and answer
  quality — not pulled by default per the "don't blindly download huge models"
  constraint; swap via `OLLAMA_MODEL` to try it.

## Switching providers

`LLM_PROVIDER=ollama|anthropic|openai` in `.env`. The system never silently falls
back to a different provider — an unconfigured or unreachable provider raises a clear
`ProviderNotConfiguredError` (surfaced as HTTP 503), never a fabricated answer.
