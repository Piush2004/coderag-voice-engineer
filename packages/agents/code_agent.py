"""Code modification agent (spec module 32/65): investigate -> propose -> [human
authorization gate] -> isolated worktree -> apply patch -> run tests -> verify -> diff.

The system NEVER writes to the user's actual working tree. A fix is only ever applied
inside a disposable `git worktree` on its own branch; the caller decides whether to
merge it. Authorization is a required, explicit boolean — there is no code path that
reaches `apply` without it.
"""
from __future__ import annotations

import shutil
import subprocess
import uuid
from dataclasses import dataclass, field
from pathlib import Path

import difflib
import re

from packages.agents.sandbox import get_sandbox
from packages.agents.state_machine import run_agent
from packages.rag.store import Repository, get_session
from packages.shared.config import settings
from packages.shared.providers import LLMMessage, get_llm_provider

# Small local models are unreliable at producing syntactically valid unified diffs
# directly (verified: qwen2.5:3b-instruct's diff output rarely applied cleanly with
# `git apply`). Asking for the complete corrected file instead — then computing the
# diff ourselves with difflib — moves the hard part (valid diff syntax) out of the
# model's hands entirely; the model only has to reproduce a file, which it does far
# more reliably. See docs/OLLAMA.md for the measured comparison.
PATCH_SYSTEM_PROMPT = """You are proposing a code fix. You have already investigated \
the codebase; the evidence is in the conversation. Respond with EXACTLY this format \
and nothing else:

FILE: <repo-relative path of the one file to change>
```
<the complete new content of that file, with your fix applied — the WHOLE file, not \
a snippet>
```

Modify only one file. If you cannot produce a confident fix from the available \
evidence, respond with exactly: NO_CONFIDENT_FIX"""

# Test generation (spec Phase 13) reuses the exact same "propose whole file, diff it
# ourselves, apply in an isolated worktree, run tests for real" pipeline as a bug fix
# — the only difference is this system prompt and how the investigation instruction
# is framed. Never claim a generated test passes without actually running it: that
# guarantee comes from apply_fix, unchanged, which always executes the real test
# command in the sandbox before reporting pass/fail.
TEST_GEN_SYSTEM_PROMPT = """You are writing a test for a specific function/class in \
a real codebase. You have already investigated the codebase and existing test style; \
the evidence is in the conversation — including, if found, an example of this \
repository's existing test file for related code, which you MUST match the style of \
(same test framework, same naming convention, same assertion style). Respond with \
EXACTLY this format and nothing else:

FILE: <repo-relative path of the test file to write to — reuse an existing test file \
for the same module if one exists, otherwise create a new one following this \
repository's existing test file naming/location convention>
```
<the complete new content of that test file — if the file already exists, this must \
be the existing content PLUS your new test(s) appended, not a replacement>
```

Write at least one meaningful test that actually exercises the target's real \
behavior (not a placeholder `assert True`). If you cannot determine the target's \
behavior confidently enough to write a real test, respond with exactly: \
NO_CONFIDENT_FIX"""


@dataclass
class FixProposal:
    diagnosis: str
    citations: list[dict]
    patch: str | None
    confident: bool
    repository_id: int = 0


# In-memory store of proposals actually produced by investigate_and_propose, keyed by
# opaque id. /api/v1/fixes/apply must look a proposal up here rather than accept
# patch text from the client — otherwise "authorized: true" is just a boolean the
# caller sets on themselves, gating nothing (found in code review: a client could
# POST an arbitrary hand-written diff straight to /fixes/apply, which would run
# auto-detected test commands via the sandbox — an RCE primitive). Process-local and
# unbounded is fine for this single-user local dev tool; a multi-user deployment
# would need a real store with TTL/eviction.
_PROPOSALS: dict[str, FixProposal] = {}


def store_proposal(proposal: FixProposal) -> str:
    proposal_id = uuid.uuid4().hex
    _PROPOSALS[proposal_id] = proposal
    return proposal_id


def get_proposal(proposal_id: str) -> FixProposal | None:
    return _PROPOSALS.get(proposal_id)


@dataclass
class FixResult:
    proposal: FixProposal
    applied: bool
    worktree_path: str | None = None
    branch: str | None = None
    test_output: str | None = None
    tests_passed: bool | None = None
    error: str | None = None
    trace: list[str] = field(default_factory=list)


_FILE_BLOCK_RE = re.compile(r"FILE:\s*(\S+)\s*```(?:\w*\n)?(.*?)```", re.DOTALL)


def investigate_and_propose(repository_id: int, conversation_id: int, instruction: str) -> FixProposal:
    """Read-only: runs the normal evidence-gathering agent loop, then asks the LLM
    for the corrected file content and computes a real unified diff ourselves
    (difflib) rather than trusting the model to hand-write diff syntax. Never
    touches disk."""
    return _propose_file_change(repository_id, conversation_id, instruction, PATCH_SYSTEM_PROMPT)


def generate_tests(repository_id: int, conversation_id: int, target_description: str) -> FixProposal:
    """Read-only: investigates the target and existing test style (via find_tests/
    inspect_file, same as any other agent run), then proposes a new/extended test
    file. Never touches disk or runs anything — apply_fix (shared with the bug-fix
    flow) is the only path that writes+executes, and only behind the same
    authorization gate."""
    instruction = (
        f"Write a test for: {target_description}. First find the target's current "
        f"behavior and look for this repository's existing test file(s) for related "
        f"code (use find_tests and inspect_file) so the new test matches the "
        f"existing style."
    )
    return _propose_file_change(repository_id, conversation_id, instruction, TEST_GEN_SYSTEM_PROMPT)


def _propose_file_change(
    repository_id: int, conversation_id: int, instruction: str, system_prompt: str
) -> FixProposal:
    """Shared mechanics behind investigate_and_propose and generate_tests: both are
    "investigate, then ask the LLM for a whole file's new content, then diff it
    ourselves" — the only real difference is the system prompt. New files (e.g. a
    test file that doesn't exist yet) are supported: an absent target is treated as
    empty content rather than rejected."""
    diagnosis_result = run_agent(repository_id, conversation_id, instruction)

    session = get_session()
    try:
        repo = session.get(Repository, repository_id)
        repo_root = Path(repo.root_path) if repo else None
    finally:
        session.close()

    llm = get_llm_provider(settings)
    patch_prompt = (
        f"Task: {instruction}\n\nDiagnosis from investigation:\n{diagnosis_result.answer}\n\n"
        f"Evidence citations: {diagnosis_result.citations}\n\n"
        "Now produce the file, as instructed."
    )
    resp = llm.complete(
        [LLMMessage(role="user", content=patch_prompt)],
        system=system_prompt,
        tools=None,
        max_tokens=3000,
    )
    raw = resp.text.strip()

    def _not_confident() -> FixProposal:
        return FixProposal(
            diagnosis_result.answer, diagnosis_result.citations, patch=None, confident=False,
            repository_id=repository_id,
        )

    if not raw or "NO_CONFIDENT_FIX" in raw or repo_root is None:
        return _not_confident()

    match = _FILE_BLOCK_RE.search(raw)
    if not match:
        return _not_confident()

    rel_path, new_content = match.group(1).strip(), match.group(2)
    if new_content.endswith("\n") is False:
        new_content += "\n"

    # The LLM supplies rel_path from its own output — never trust it as a safe
    # relative path. `Path("/repo") / "/etc/passwd"` resolves to "/etc/passwd" (the
    # `/` operator discards the left side entirely for an absolute right side), and
    # "../../etc/passwd" would escape repo_root even without that quirk. Resolve and
    # verify containment before ever touching the target (found in code review: this
    # was reachable as an arbitrary-file-read via the *read-only* propose endpoint).
    repo_root_resolved = repo_root.resolve()
    target = (repo_root / rel_path).resolve()
    try:
        target.relative_to(repo_root_resolved)
    except ValueError:
        return _not_confident()

    is_new_file = not target.exists()
    old_content = "" if is_new_file else target.read_text(encoding="utf-8")
    if old_content == new_content:
        return _not_confident()

    diff = "".join(
        difflib.unified_diff(
            old_content.splitlines(keepends=True),
            new_content.splitlines(keepends=True),
            fromfile="/dev/null" if is_new_file else f"a/{rel_path}",
            tofile=f"b/{rel_path}",
        )
    )
    return FixProposal(
        diagnosis=diagnosis_result.answer, citations=diagnosis_result.citations, patch=diff, confident=True,
        repository_id=repository_id,
    )


def apply_fix(repository_id: int, proposal: FixProposal, run_test_command: list[str] | None = None) -> FixResult:
    """WRITE + EXECUTE path. Requires an already-produced, confident FixProposal —
    callers (the API layer) are responsible for only invoking this after explicit
    user authorization; this function does not re-check authorization itself so it
    stays testable in isolation, but it is never wired to a route without that gate
    (see apps/backend/main.py::apply_code_fix)."""
    trace = []
    if not proposal.confident or not proposal.patch:
        return FixResult(proposal=proposal, applied=False, error="No confident patch was proposed.")

    session = get_session()
    try:
        repo = session.get(Repository, repository_id)
        if repo is None:
            return FixResult(proposal=proposal, applied=False, error="Repository not found.")
        repo_root = repo.root_path
    finally:
        session.close()

    if not (Path(repo_root) / ".git").exists():
        return FixResult(
            proposal=proposal, applied=False,
            error="Repository is not a git repo — isolated worktree patching requires git.",
        )

    branch = f"coderag/fix-{uuid.uuid4().hex[:8]}"
    worktree_path = str(Path(repo_root).parent / f".coderag-worktrees" / branch.replace("/", "-"))
    Path(worktree_path).parent.mkdir(parents=True, exist_ok=True)
    trace.append(f"Creating isolated worktree on branch {branch}...")

    try:
        subprocess.run(
            ["git", "worktree", "add", "-b", branch, worktree_path, "HEAD"],
            cwd=repo_root, capture_output=True, text=True, timeout=30, check=True,
        )
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired) as e:
        return FixResult(proposal=proposal, applied=False, trace=trace, error=f"Failed to create worktree: {e}")

    patch_file = Path(worktree_path) / ".coderag-proposed.patch"
    patch_file.write_text(proposal.patch, encoding="utf-8")
    trace.append("Applying patch...")

    check = subprocess.run(
        ["git", "apply", "--check", str(patch_file)], cwd=worktree_path, capture_output=True, text=True,
    )
    if check.returncode != 0:
        _cleanup_worktree(repo_root, worktree_path)
        return FixResult(
            proposal=proposal, applied=False, trace=trace,
            error=f"Patch does not apply cleanly: {check.stderr[:2000]}",
        )
    apply = subprocess.run(
        ["git", "apply", str(patch_file)], cwd=worktree_path, capture_output=True, text=True,
    )
    patch_file.unlink(missing_ok=True)
    if apply.returncode != 0:
        _cleanup_worktree(repo_root, worktree_path)
        return FixResult(proposal=proposal, applied=False, trace=trace, error=f"git apply failed: {apply.stderr[:2000]}")

    trace.append("Patch applied. Running tests in sandbox...")
    tests_passed = None
    test_output = None
    command = run_test_command or _detect_test_command(worktree_path)
    if command:
        try:
            sandbox = get_sandbox(settings.sandbox_backend)
            result = sandbox.run(command, cwd=worktree_path, timeout=120)
            tests_passed = result.exit_code == 0 and not result.timed_out
            test_output = (result.stdout + "\n" + result.stderr)[-4000:]
            trace.append(f"Tests {'passed' if tests_passed else 'failed'}.")
        except Exception as e:  # noqa: BLE001 — must not leak the worktree/branch on any failure mode
            _cleanup_worktree(repo_root, worktree_path)
            return FixResult(
                proposal=proposal, applied=True, worktree_path=None, branch=None,
                trace=trace, error=f"Test execution failed unexpectedly (worktree cleaned up): {e}",
            )
    else:
        trace.append("No test command detected — skipped automatic verification.")

    return FixResult(
        proposal=proposal, applied=True, worktree_path=worktree_path, branch=branch,
        test_output=test_output, tests_passed=tests_passed, trace=trace,
    )


def get_diff(worktree_path: str) -> str:
    result = subprocess.run(
        ["git", "diff", "HEAD"], cwd=worktree_path, capture_output=True, text=True, timeout=15,
    )
    return result.stdout


def _detect_test_command(worktree_path: str) -> list[str] | None:
    root = Path(worktree_path)
    if (root / "pytest.ini").exists() or list(root.glob("tests/**/test_*.py")):
        return ["python", "-m", "pytest", "-q"]
    if (root / "package.json").exists():
        return ["npm", "test", "--silent"]
    return None


def _cleanup_worktree(repo_root: str, worktree_path: str) -> None:
    try:
        subprocess.run(["git", "worktree", "remove", "--force", worktree_path], cwd=repo_root,
                        capture_output=True, text=True, timeout=30)
    except Exception:  # noqa: BLE001
        shutil.rmtree(worktree_path, ignore_errors=True)
