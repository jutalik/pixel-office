"""Adapter <-> normalize conformance: no dead states, no unmapped kinds.

Reads the single adapter registry — so a CLI added in adapters/<cli>.py is
guarded here automatically.
"""
import pytest

from pixel_office.adapters import registry
from pixel_office.telemetry.contract import ACTIVITY_STATES

_ADAPTERS = registry.all_adapters()
_WITH_KINDS = [a for a in _ADAPTERS if a.kinds]
_WITH_EMITTED = [a for a in _ADAPTERS if a.emitted_kinds]


@pytest.mark.parametrize("a", _WITH_KINDS, ids=lambda a: a.name)
def test_every_table_kind_maps_to_a_real_activity(a):
    for kind, state in a.kinds.items():
        assert state in ACTIVITY_STATES, f"{a.name}:{kind} -> {state} not a valid activity"


@pytest.mark.parametrize("a", _WITH_EMITTED, ids=lambda a: a.name)
def test_every_emitted_kind_is_in_the_table(a):
    # a kind an adapter can produce must map to a state (never a dead avatar)
    for kind in a.emitted_kinds:
        assert kind in a.kinds, f"{a.name} emits {kind} but it's not in the normalize table"
        assert a.kinds[kind] in ACTIVITY_STATES


@pytest.mark.parametrize("a", _WITH_EMITTED, ids=lambda a: a.name)
def test_tailer_derivable_matches_emitted_kinds(a):
    produced = {a.kinds[k] for k in a.emitted_kinds}
    assert set(a.tailer_derivable) == produced


def test_provisional_adapters_are_honestly_unsupported():
    # agy (SQLite, unverified) and hermes (hooks-only) must not claim a tailer
    for name in ("agy", "hermes"):
        a = registry.get(name)
        assert a.normalize_supported is False
        assert a.has_verified_tailer is False
