# Evaluation

Two separate harnesses measure two separate things — conflating them would hide
whether a bad answer is a retrieval problem or a reasoning problem.

## 1. Retrieval-only: `evaluation/retrieval_benchmark.py`

Bypasses the LLM entirely — calls `packages/rag/retrieval.py::hybrid_search`
directly against a small synthetic fixture repo with known ground-truth file
locations. Reports **Recall@K** (did the right file appear in the top K?) and
**MRR** (how highly ranked was it?). Fast (~5s), deterministic, safe to run on every
retrieval change as a regression gate (spec module 30) — a change that drops Recall@5
below the existing baseline should be treated as a regression, not shipped.

Last measured result: **Recall@5 = 1.00, MRR = 1.00** (n=6 queries — intentionally
small and self-authored, not a claim of production-scale accuracy; extend `BENCHMARK`
in the script as real usage surfaces harder cases).

## 2. Full agent: `evaluation/agent_eval.py`

Exercises the real, live `/api/v1/chat` endpoint — real Ollama inference, real tool
calls, real retrieval, no mocks. 28 cases across 10 categories (architecture, code
navigation, dependency, debugging, git, RAG, agent, security, no-answer, multi-hop),
each scored automatically:
- **grounded** cases: pass if the answer or citations reference the expected
  evidence keywords.
- **no_answer** cases: pass if the model says it can't determine the answer *and*
  doesn't fabricate citations.
- **resist_injection** cases: pass if the model doesn't comply with an embedded
  malicious instruction.

This is a **behavioral** eval, not exact-match — spec module 31 explicitly calls for
evaluating evidence/task success rather than wording, since a local model's phrasing
varies run to run.

Real measured results (not fabricated) are in [PROJECT_STATUS.md](PROJECT_STATUS.md),
along with the raw per-case output. Run it yourself:
```bash
apps/backend/.venv/Scripts/python.exe evaluation/agent_eval.py           # all 28 cases
apps/backend/.venv/Scripts/python.exe evaluation/agent_eval.py --limit 5 # quick smoke test
```
Expect this to take minutes on CPU inference — see [OLLAMA.md](OLLAMA.md) for measured
per-query latency.

## 3. Ad hoc probe: `evaluation/adhoc_probe.py`

The exact 10 questions from the original task brief, run once for a qualitative
spot-check with full answer text printed (not just pass/fail). Useful for eyeballing
answer quality, not for regression tracking.

## What's not built

A synthetic-question-generation pipeline (spec module 38), an LLM-judge for
faithfulness/groundedness scoring (spec module 36), and voice-specific latency
benchmarks beyond the plain `/chat` latency already captured — see
[PROJECT_STATUS.md](PROJECT_STATUS.md).
