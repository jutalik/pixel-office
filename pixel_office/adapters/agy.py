"""agy = Antigravity CLI (Google), the successor to gemini-cli. PROVISIONAL.

Auth is a disk token under ~/.gemini/antigravity-cli/; sessions are a SQLite
conversations DB (not JSONL), so agy uses the generic SqliteSessionSource. The
row mapper stays UNREGISTERED (kinds empty, no parser) until verified against a
live agy install's schema — so doctor reports agy as hooks-capable + a SQLite
store, but never as a tailer/normalize source. See docs/CLI-MATRIX.md.

agy isolates by HOME; agy-ha runs each session under
HOME=~/.claude-ha/agy-sessions/<id>, whose DB is at
<that-home>/.gemini/antigravity-cli/*.db (globbing those is a watcher extension).
"""
from __future__ import annotations

from pathlib import Path

from .base import Adapter

ADAPTER = Adapter(
    name="agy",
    kinds={},                     # provisional — unverified vocabulary
    emitted_kinds=frozenset(),
    extra_bin_dirs=(Path.home() / ".local" / "bin",),
    env_home=None,                # no dedicated home var; isolates by HOME
    home=Path.home() / ".gemini",
    session_kind="sqlite",
    session_sqlite="antigravity-cli/*.db",
    sqlite_mapper=None,           # unverified -> not a tailer source yet
    hooks_capable=True,
    hook_kind="settings",
)
