"""Hermes adapter — hooks-only (a plugin), no session-file store located.

Orca ships a hermes hook plugin under ~/.hermes/plugins/, so hermes is
hook-capable; no tailable session store was found, so it has no tailer path.
"""
from __future__ import annotations

from pathlib import Path

from .base import Adapter

ADAPTER = Adapter(
    name="hermes",
    kinds={},                     # no tailer/normalize table (hooks would add one)
    emitted_kinds=frozenset(),
    env_home="HERMES_HOME",
    home=Path.home() / ".hermes",
    session_kind="none",
    hooks_capable=True,
    hook_kind="plugin",
)
