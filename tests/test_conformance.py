"""Adapter <-> normalize conformance: no dead states, no unmapped kinds."""
import pytest

from pixel_office.telemetry.adapters import EMITTED_KINDS
from pixel_office.telemetry.contract import ACTIVITY_STATES
from pixel_office.telemetry.normalize import TAILER_DERIVABLE, _TABLES, normalize


@pytest.mark.parametrize("cli", sorted(_TABLES))
def test_every_table_kind_maps_to_a_real_activity(cli):
    for kind, state in _TABLES[cli].items():
        assert state in ACTIVITY_STATES, f"{cli}:{kind} -> {state} not a valid activity"


@pytest.mark.parametrize("cli", sorted(EMITTED_KINDS))
def test_every_emitted_kind_is_normalized(cli):
    # a kind an adapter can produce must map to a state (never None -> dead avatar)
    for kind in EMITTED_KINDS[cli]:
        assert normalize(cli, kind) is not None, f"{cli} emits {kind} but normalize returns None"


@pytest.mark.parametrize("cli", sorted(TAILER_DERIVABLE))
def test_tailer_derivable_matches_emitted_kinds(cli):
    if cli not in EMITTED_KINDS:
        return
    produced = {normalize(cli, k) for k in EMITTED_KINDS[cli]}
    declared = set(TAILER_DERIVABLE[cli])
    # what the tailer can actually derive must equal what we advertise it derives
    assert produced == declared, f"{cli}: tailer produces {produced}, advertises {declared}"
