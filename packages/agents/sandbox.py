"""Sandbox interface for running repository code/tests (spec module 23/26).

HONEST LIMITATION: this environment has no Docker (docs/INITIAL_AUDIT.md), so
`LocalSubprocessSandbox` is a subprocess with a timeout and an isolated temp
workspace — NOT real filesystem/network isolation. It is explicitly not claimed to be
a secure sandbox against adversarial code; it protects against runaway/hanging
processes, not against a malicious repository. A Docker-backed `Sandbox` is the
documented production requirement before running untrusted third-party repositories
(docs/SECURITY.md).
"""
from __future__ import annotations

import subprocess
from abc import ABC, abstractmethod
from dataclasses import dataclass


@dataclass
class SandboxResult:
    exit_code: int
    stdout: str
    stderr: str
    timed_out: bool


class Sandbox(ABC):
    @abstractmethod
    def run(self, command: list[str], cwd: str, timeout: int = 60) -> SandboxResult: ...


class LocalSubprocessSandbox(Sandbox):
    """Best-effort isolation: temp cwd, wall-clock timeout, no shell interpolation
    (command is always an argv list, never a string — no injection surface). Real
    filesystem/network restriction requires the Docker backend (not available in this
    environment, see module docstring)."""

    def run(self, command: list[str], cwd: str, timeout: int = 60) -> SandboxResult:
        try:
            proc = subprocess.run(
                command,
                cwd=cwd,
                capture_output=True,
                text=True,
                timeout=timeout,
                shell=False,
            )
            return SandboxResult(proc.returncode, proc.stdout[-8000:], proc.stderr[-8000:], timed_out=False)
        except subprocess.TimeoutExpired as e:
            return SandboxResult(-1, (e.stdout or ""), (e.stderr or "") + "\n[timed out]", timed_out=True)
        except FileNotFoundError as e:
            return SandboxResult(-1, "", str(e), timed_out=False)


def get_sandbox(backend: str) -> Sandbox:
    if backend == "subprocess":
        return LocalSubprocessSandbox()
    raise ValueError(
        f"Unknown sandbox backend: {backend}. Docker backend is not implemented in "
        f"this environment (no Docker installed — see docs/INITIAL_AUDIT.md)."
    )
