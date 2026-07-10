import pytest

from pixel_office.telemetry.contract import (
    MAX_META_STRING, RawEvent, SCHEMA_VERSION, TRUNCATION_MARK, sanitize_meta,
)


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


def test_seq_zero_allowed():
    assert RawEvent.from_dict(_base(seq=0)).seq == 0


def test_seq_rejects_bool_and_fractional():
    with pytest.raises(ValueError):
        RawEvent.from_dict(_base(seq=True))
    with pytest.raises(ValueError):
        RawEvent.from_dict(_base(seq=1.9))
    # JSON transports may float-encode integers; whole floats are accepted
    assert RawEvent.from_dict(_base(seq=5.0)).seq == 5
    assert RawEvent.from_dict(_base(seq="7")).seq == 7


def test_source_confidence_derived_from_source():
    assert RawEvent.from_dict(_base(source="hook")).source_confidence == "high"
    assert RawEvent.from_dict(_base(source="tailer")).source_confidence == "low"


def test_source_confidence_explicit_and_validated():
    assert RawEvent.from_dict(_base(source_confidence="low")).source_confidence == "low"
    with pytest.raises(ValueError):
        RawEvent.from_dict(_base(source_confidence="medium"))


# ---- sanitize_meta: recursive, aliased, bounded --------------------------------

def test_meta_sanitized_drops_secrets_and_prompts_top_level():
    ev = RawEvent.from_dict(_base(meta={"prompt": "hi", "token": "x", "tool": "Bash", "count": 3}))
    assert ev.meta == {"tool": "Bash", "count": 3}


def test_sanitize_meta_case_insensitive():
    assert sanitize_meta({"PROMPT": "x", "ok": 1}) == {"ok": 1}


def test_sanitize_meta_nested_dict():
    assert sanitize_meta({"detail": {"prompt": "leak", "password": "hunter2", "n": 1}}) \
        == {"detail": {"n": 1}}


def test_sanitize_meta_list_of_dicts():
    assert sanitize_meta({"items": [{"prompt": "leak"}, {"ok": True}]}) \
        == {"items": [{}, {"ok": True}]}


def test_sanitize_meta_key_aliases():
    got = sanitize_meta({"prompt ": "leak", "toolInput": "leak", "userPrompt": "leak",
                         "command": "rm -rf /", "keep": "ok"})
    assert got == {"keep": "ok"}


def test_sanitize_meta_string_cap_including_marker():
    got = sanitize_meta({"note": "x" * 100_000})
    assert len(got["note"]) == MAX_META_STRING
    assert got["note"].endswith(TRUNCATION_MARK)


def test_sanitize_meta_numeric_and_key_bounds():
    got = sanitize_meta({
        "big": 10 ** 100, "inf": float("inf"), "nan": float("nan"),
        ("k" * 500): "dropped-by-key-length", "ok": 7,
    })
    assert got == {"ok": 7}


def test_sanitize_meta_depth_cap():
    deep = {"a": {"b": {"c": {"d": {"prompt": "leak"}}}}}
    got = sanitize_meta(deep)
    # nothing beyond MAX_META_DEPTH survives, so the leaked prompt is gone
    assert "prompt" not in repr(got)


def test_sanitize_meta_drops_unexpected_types():
    got = sanitize_meta({"blob": b"\x00\x01", "fn": len, "ok": 1.5})
    assert got == {"ok": 1.5}


def test_sanitize_meta_idempotent():
    once = sanitize_meta({"detail": {"n": 1}, "note": "x" * 300})
    assert sanitize_meta(once) == once


def test_sanitize_meta_non_dict_input():
    assert sanitize_meta(None) == {}
    assert sanitize_meta("string") == {}
