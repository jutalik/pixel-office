"""Company adapter — normalizes employee-activity events from the org runtime.

Not a CLI (is_cli=False, so `po doctor` skips it) — it exists only so employees
emitted by OrgRuntime (cli="company") normalize to avatar states through the same
reducer as the CLI agents.
"""
from __future__ import annotations

from .base import Adapter

KINDS = {
    "Assigned": "working",
    "Working": "working",
    "Waiting": "waiting",
    "Blocked": "blocked",
    "Done": "done",
}

ADAPTER = Adapter(
    name="company",
    kinds=KINDS,
    emitted_kinds=frozenset(),   # pushed live by the runtime, not tailed
    session_kind="none",
    is_cli=False,                # a pseudo-source, not an installable CLI
    hooks_capable=False,
)
