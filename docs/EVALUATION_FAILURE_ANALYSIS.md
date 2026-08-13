# Evaluation Failure Analysis — 29-case benchmark, 18/29 (62%)

Source data: `evaluation/agent_eval_results.json` (real run, real answers quoted
verbatim below — nothing paraphrased or reconstructed from memory). Model:
`qwen2.5:3b-instruct` via Ollama. All 11 failures analyzed individually.

## Failure category taxonomy (counts)

| Category | Count | Cases |
|---|---|---|
| TOOL_SELECTION_FAILURE (skipped search entirely) | 6 | #2, #4, #5, #8, #10, #11 |
| MODEL_REASONING_FAILURE (answered from general LLM knowledge, not repo evidence) | 2 | #9, #10 |
| EVIDENCE_ATTRIBUTION_FAILURE (had citations, misattributed the claim) | 1 | #3 |
| PROMPT_FAILURE (malformed/incomplete tool call) | 1 | #7 |
| EVALUATION_FAILURE (benchmark keyword list too strict for a valid answer) | 1 | #1 |

(Two cases, #9 and #10, exhibit both zero-tool-calls *and* general-knowledge
reasoning — counted once each in the primary bucket, noted as overlapping.)

**Headline finding: 8 of 11 failures (73%) involve the model never calling a tool
at all**, despite `SYSTEM_PROMPT` in `packages/agents/state_machine.py` explicitly
stating "You MUST call at least one tool before giving a final answer." A 3B model
does not reliably obey a prompt-level instruction to always act — this must be
enforced at the orchestrator level, not left to the prompt. This directly drove the
Phase 2 fix (see bottom of this doc).

---

## Case-by-case

### #1 — "Explain the overall architecture of this repository." — EVALUATION_FAILURE (borderline)
- **Citations**: 6 (search_code was called)
- **Actual answer**: "CONFIRMED: The architecture... is described in detail in the
  files `README.md`, `docs/ARCHITECTURE.md`, and `docs/FINAL_ACCEPTANCE_REPORT.md`..."
- **Root cause**: The agent *did* search and *did* answer grounded in real citations
  — it just cited documentation files rather than the `packages/agents`/`packages/rag`
  directories my benchmark's `expected_evidence` keyword list required. Citing the
  architecture docs for an architecture question is a defensible answer, not a
  fabrication.
- **Fix category**: Evaluation methodology (benchmark's keyword list was too narrow),
  not a real agent defect. Left as a known benchmark limitation rather than "fixed" —
  fixing this properly means a judge that checks semantic correctness, not keywords
  (see docs/EVALUATION.md's documented gap: no LLM-judge scorer exists yet).

### #2 — "Where is the tree-sitter parser defined?" — TOOL_SELECTION_FAILURE
- **Citations**: 0
- **Actual answer**: "UNKNOWN: The repository does not contain any information
  about the tree-sitter parser definition."
- **Root cause**: Never called `search_code` or `search_symbols`. Gave up
  immediately despite `packages/code_intelligence/parser.py` being a direct,
  discoverable match for "parser" by both filename and content.
- **Fix category**: Orchestration (force retrieval before UNKNOWN is accepted).

### #3 — "Which function performs code-aware chunking?" — EVIDENCE_ATTRIBUTION_FAILURE
- **Citations**: 3 (search_code was called and returned real results, including
  `chunk_file` in `packages/rag/chunker.py` per the retrieval benchmark's own
  verified behavior on this exact query)
- **Actual answer**: "CONFIRMED: The function that performs code-aware chunking is
  `search_code`."
- **Root cause**: The model had correct evidence in front of it and named the wrong
  symbol — `search_code` is the *retrieval tool itself*, not a chunking function.
  This is a genuine misread/misattribution of retrieved evidence, the most concerning
  failure mode since it produces a confident, wrong, specific claim rather than a
  hedge.
- **Fix category**: Evidence attribution (Phase 3 — require the model to reference
  evidence by an explicit ID rather than free-recall the function name from a long
  tool-result blob).

### #4 — "What does packages/agents/state_machine.py import from packages/rag?" — TOOL_SELECTION_FAILURE
- **Citations**: 0
- **Actual answer**: "UNKNOWN\n\nThere is no evidence of an import statement from
  `packages/rag` in `packages/agents/state_machine.py`."
- **Root cause**: Never called `inspect_file` or `search_code` on the named file.
  Confidently asserted absence of evidence it never looked for — arguably worse than
  a plain UNKNOWN, since it implies a search happened.
- **Fix category**: Orchestration.

### #5 — "What happens when an LLM provider is unavailable?" — TOOL_SELECTION_FAILURE / MODEL_REASONING_FAILURE
- **Citations**: 0
- **Actual answer**: "...does not provide enough context or specific details to
  search for answers within the given repository. We would need more information
  such as code snippets..."
- **Root cause**: The model reasoned itself out of searching at all, treating a
  perfectly searchable question ("LLM provider unavailable" → `ProviderNotConfiguredError`
  in `packages/shared/providers.py`) as requiring clarification first.
- **Fix category**: Orchestration.

### #6 — "Why would /api/v1/chat return a 503?" — TOOL_SELECTION_FAILURE (wrong tool)
- **Citations**: 0
- **Actual answer**: "The search did not return any relevant commit messages or
  changed files, so there's no evidence to confirm why /api/v1/chat might be
  returning a 503."
- **Root cause**: The answer text implies `search_git_history` was called (it
  references "commit messages" and "changed files"), not `search_code` —
  a debugging-flavored question triggered a Git search instead of a code search,
  which was the wrong first move for this specific question.
- **Fix category**: Query routing (Phase 5 — a "why does X return error code Y"
  question should prioritize code/symbol search over Git search).

### #7 — "What retrieval algorithm combines semantic and lexical search here?" — PROMPT_FAILURE
- **Citations**: 0
- **Actual answer**: "It seems like the query parameter is missing. Let's try again
  with a proper query..."
- **Root cause**: This reads as the model receiving a tool-error result (a call to
  `search_code` with a missing/empty `query` argument, since that's a required field
  in `TOOL_SCHEMAS`) and then surfacing that confusion directly to the user instead
  of recovering by retrying with a real query.
- **Fix category**: Orchestration — when a tool call fails validation, the
  orchestrator should feed a corrective instruction back to the model rather than let
  a raw tool error become the final answer.

### #8 — "What embedding model is used by default?" — TOOL_SELECTION_FAILURE
- **Citations**: 0
- **Actual answer**: "UNKNOWN: The information about the default embedding model
  used by CodeRAG is not contained in the repository."
- **Root cause**: Never searched. `fastembed`/`BAAI/bge-small-en-v1.5` is directly
  named in `packages/shared/providers.py` and `docs/DECISIONS.md`.
- **Fix category**: Orchestration.

### #9 — "How does the agent avoid infinite tool-calling loops?" — MODEL_REASONING_FAILURE
- **Citations**: 0
- **Actual answer**: "Agents like me typically include mechanisms to prevent such
  loops, often through checks that track whether a function has already been called
  recently..." (continues for a full paragraph of generic, plausible-sounding,
  **ungrounded** description of how agents in general prevent loops)
- **Root cause**: Answered fluently and plausibly from general training knowledge
  about how agent systems typically work, without ever looking at this repository's
  actual `max_iterations`/`max_tool_calls`/dedupe logic in `state_machine.py`. This
  is the single most dangerous failure mode in the whole set — a confident, readable,
  generically-true-sounding answer that is not actually about this codebase at all.
- **Fix category**: Orchestration (evidence-first enforcement) — this is exactly the
  failure Phase 2 targets.

### #10 — "Does the agent expose its internal chain-of-thought to the user?" — MODEL_REASONING_FAILURE
- **Citations**: 0
- **Actual answer**: "None of the provided tools allow inspecting or exposing a
  tool's internal chain-of-thought... The appropriate way to get this information
  would be to ask the developer or architect responsible for the codebase."
- **Root cause**: Same pattern as #9 — reasoned about its own tool list in the
  abstract rather than searching `state_machine.py`'s `trace` mechanism, which
  directly answers this question (concise status lines only, no raw reasoning).
- **Fix category**: Orchestration.

### #11 — "How does this system prevent path traversal during repository indexing?" — TOOL_SELECTION_FAILURE
- **Citations**: 0
- **Actual answer**: "UNKNOWN: The provided codebase does not contain any
  information related to how the system prevents path traversal..."
- **Root cause**: Never searched. `packages/rag/indexer.py::discover_files`'s
  `relative_to()` containment check directly answers this and is easily found by
  `search_code("path traversal")` — verified in this same session, this exact
  query against `/api/v1/search` correctly surfaces `indexer.py`.
- **Fix category**: Orchestration.

---

## Fix priority (by leverage)

1. **Orchestrator-level forced retrieval** (fixes root cause of 8/11 failures) —
   implemented in Phase 2, see `packages/agents/state_machine.py`.
2. **Tool-call validation recovery** (fixes #7) — same Phase 2 change: a failed/
   malformed tool call now gets a corrective retry instead of surfacing raw error
   text as the final answer.
3. **Evidence-ID attribution** (fixes #3-style misattribution) — larger change,
   deferred pending measurement of how much the Phase 2 fix alone improves things
   first (spec's own instruction: measure before adding complexity).
4. **Query-routing by category** (fixes #6-style wrong-tool-first) — deferred for
   the same reason.
5. **Benchmark keyword strictness** (#1) — left as a documented benchmark
   limitation; not an agent defect.
