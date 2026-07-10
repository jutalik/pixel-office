import pytest

from pixel_office.telemetry.contract import RawEvent, sanitize_meta, SCHEMA_VERSION


def _base(**kw):
    d = dict(host_id="h1", cli="claude", session_id="s1", agent_id="a1",
             seq=1, ts="2026-07-10T00:00:00Z", source="hook", kind="PreToolUse")
    d.update(kw)
    return d


def test_from_dict_ok():
    ev = RawEvent.from_dict(_base())
    assert ev.cli == "claude" and ev.seq == 1 and ev.schema_version == SCHEMA_VERSION


def test_missing_field_raises():
    d = _base()
    del d["session_id"]
    with pytest.raises(ValueError):
        RawEvent.from_dict(d)


def test_bad_source_raises():
    with pytest.raises(ValueError):
        RawEvent.from_dict(_base(source="magic"))


def test_seq_must_be_int():
    with pytest.raises(ValueError):
        RawEvent.from_dict(_base(seq="notanumber"))


def test_negative_seq_raises():
    with pytest.raises(ValueError):
        RawEvent.from_dict(_base(seq=-1))


def test_meta_sanitized_drops_secrets_and_prompts():
    ev = RawEvent.from_dict(_base(meta={"prompt": "hi", "token": "x", "tool": "Bash", "count": 3}))
    assert ev.meta == {"tool": "Bash", "count": 3}


def test_sanitize_meta_case_insensitive():
    assert sanitize_meta({"PROMPT": "x", "ok": 1}) == {"ok": 1}
