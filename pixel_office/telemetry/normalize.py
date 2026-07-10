"""Normalization facade over the adapter registry (single source of truth).

The per-CLI kind->activity tables now live in `adapters/<cli>.py`. This module
keeps the stable public API the rest of the code and the tests import.
"""
from __future__ import annotations

from typing import Optional

from ..adapters import registry


def normalize(cli: str, kind: str) -> Optional[str]:
    return registry.normalize(cli, kind)


def known_clis() -> tuple:
    return registry.known_clis()


# Back-compat views built from the registry (per-CLI data lives in adapters/).
#: {cli: {kind: activity}} for CLIs that have a normalize table
_TABLES = {a.name: dict(a.kinds) for a in registry.all_adapters() if a.kinds}
#: {cli: (activity, ...)} the tailer can actually derive
TAILER_DERIVABLE = {a.name: a.tailer_derivable
                    for a in registry.all_adapters() if a.emitted_kinds}
