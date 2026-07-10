"""The adapter registry — the single lookup every consumer reads from.

doctor, normalize, the tailer, the SQLite source, and the conformance test all
go through here, so a CLI is defined in exactly one place (`adapters/<cli>.py`).
"""
from __future__ import annotations

from pathlib import Path
from typing import Dict, Optional, Tuple

from .agy import ADAPTER as _agy
from .base import Adapter
from .claude import ADAPTER as _claude
from .codex import ADAPTER as _codex
from .grok import ADAPTER as _grok
from .hermes import ADAPTER as _hermes

# Registration order = display order in `po doctor`.
_ALL = (_claude, _codex, _grok, _agy, _hermes)
ADAPTERS: Dict[str, Adapter] = {a.name: a for a in _ALL}


def get(cli: str) -> Optional[Adapter]:
    return ADAPTERS.get(cli)


def all_adapters() -> Tuple[Adapter, ...]:
    return _ALL


# ---- normalization -----------------------------------------------------------

def normalize(cli: str, kind: str) -> Optional[str]:
    a = ADAPTERS.get(cli)
    return a.kinds.get(kind) if a else None


def known_clis() -> Tuple[str, ...]:
    """CLIs with a usable normalize table (a verified tailer or hook source)."""
    return tuple(a.name for a in _ALL if a.normalize_supported)


def tailer_derivable(cli: str) -> Tuple[str, ...]:
    a = ADAPTERS.get(cli)
    return a.tailer_derivable if a else ()


# ---- tailing -----------------------------------------------------------------

def parser_for(cli: str):
    a = ADAPTERS.get(cli)
    return a.parse_line if a else None


def session_id_for(cli: str, path: Path) -> str:
    a = ADAPTERS.get(cli)
    return a.session_id_for(path) if a else path.stem


def sqlite_mapper_for(cli: str):
    a = ADAPTERS.get(cli)
    return a.sqlite_mapper if a else None
