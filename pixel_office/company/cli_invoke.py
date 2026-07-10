"""Real CLI invocation for CLIExecutor — the only path that spends tokens.

Builds the headless command for each supported CLI and runs it via an injectable
`runner` (real `subprocess.run` in production; a fake in tests, so the wiring is
verified at ZERO tokens). Resolves each CLI's binary through the adapter registry
(honoring extra paths like ~/.grok/bin). Fail-open: a missing binary, timeout, or
non-zero exit yields "", which CLIExecutor treats as Blocked (never a fake result).
"""
from __future__ import annotations

import subprocess
from typing import Callable, Optional, Tuple

from .. import doctor
from ..adapters import registry

DEFAULT_TIMEOUT_S = 180


def _binary(cli: str) -> Optional[str]:
    a = registry.get(cli)
    return doctor.which(a) if a else None


def _build(cli: str, binary: str, prompt: str) -> Tuple[list, Optional[str]]:
    """Return (argv, stdin). Prompt goes on stdin where the CLI supports it
    (safer for length/escaping); grok takes it as a -p argument."""
    if cli == "claude":
        return ([binary, "--print"], prompt)                                  # stdin
    if cli == "codex":
        return ([binary, "exec", "--skip-git-repo-check", "-s", "read-only", "-"], prompt)  # stdin
    if cli == "grok":
        return ([binary, "-m", "grok-4", "--disable-web-search", "-p", prompt], None)       # arg
    return ([binary, prompt], None)


def make_subprocess_invoke(*, runner: Callable = subprocess.run,
                           timeout_s: float = DEFAULT_TIMEOUT_S) -> Callable[[str, str], str]:
    """Return an invoke_fn(cli, prompt) -> str for CLIExecutor."""
    def invoke(cli: str, prompt: str) -> str:
        binary = _binary(cli)
        if not binary:
            return ""   # CLI not installed → Blocked (executor stays honest)
        argv, stdin = _build(cli, binary, prompt)
        try:
            result = runner(argv, input=stdin, capture_output=True, text=True, timeout=timeout_s)
        except Exception:
            return ""   # timeout / spawn error → fail open
        if getattr(result, "returncode", 0) != 0:
            return ""
        return (getattr(result, "stdout", "") or "").strip()
    return invoke
