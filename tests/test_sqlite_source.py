import sqlite3

import pytest

from pixel_office.telemetry.reducer import reduce_all
from pixel_office.telemetry.sqlite_source import (
    SqliteSessionSource, known_mappers, register_mapper,
)

TS = "2026-07-10T05:00:00Z"

# a test-only mapper (agy's real schema must be verified against a live install
# before a mapper is registered for it — this proves the machinery, not agy)
QUERY = "SELECT rowid AS rowid, ts, kind, sess FROM events WHERE rowid > :watermark ORDER BY rowid"


def _map(row):
    return (row["kind"], row["ts"], row["sess"], {})


def _make_db(path, rows):
    conn = sqlite3.connect(path)
    conn.execute("CREATE TABLE events (ts TEXT, kind TEXT, sess TEXT)")
    conn.executemany("INSERT INTO events (ts, kind, sess) VALUES (?, ?, ?)", rows)
    conn.commit()
    conn.close()


def _source(path, **kw):
    return SqliteSessionSource(path, host_id="h1", cli="claude", query=QUERY, mapper=_map, **kw)


def test_polls_new_rows_incrementally(tmp_path):
    db = tmp_path / "c.db"
    _make_db(db, [(TS, "UserPromptSubmit", "s1")])
    src = _source(db)
    first = src.poll()
    assert [e.kind for e in first] == ["UserPromptSubmit"]
    assert src.poll() == []  # nothing new
    conn = sqlite3.connect(db)
    conn.execute("INSERT INTO events VALUES (?,?,?)", (TS, "Stop", "s1"))
    conn.commit(); conn.close()
    second = src.poll()
    assert [e.kind for e in second] == ["Stop"]
    assert second[0].seq > first[0].seq  # forward-only minted seq


def test_reduces_to_expected_state(tmp_path):
    db = tmp_path / "c.db"
    _make_db(db, [(TS, "UserPromptSubmit", "s1"), (TS, "Stop", "s1")])
    events = _source(db).poll()
    st = reduce_all(events)
    assert st.agents[("h1", "claude", "s1", "main")].activity == "done"


def test_missing_db_fails_open(tmp_path):
    assert _source(tmp_path / "nope.db").poll() == []


def test_readonly_does_not_lock_writer(tmp_path):
    db = tmp_path / "c.db"
    _make_db(db, [(TS, "PreToolUse", "s1")])
    src = _source(db)
    src.poll()
    # a concurrent writer can still write while the source holds no lock
    conn = sqlite3.connect(db, timeout=1)
    conn.execute("INSERT INTO events VALUES (?,?,?)", (TS, "Stop", "s1"))
    conn.commit(); conn.close()  # would raise 'database is locked' if we held a lock


def test_state_roundtrip_no_reemit(tmp_path):
    db = tmp_path / "c.db"
    _make_db(db, [(TS, "PreToolUse", "s1")])
    src = _source(db)
    src.poll()
    state = src.state_dict()
    src2 = _source(db)
    src2.load_state(state)
    assert src2.poll() == []  # already-seen rows are not re-emitted


def test_unverified_cli_has_no_mapper():
    # agy must NOT have a registered mapper (its schema is unverified)
    assert "agy" not in known_mappers()
    with pytest.raises(ValueError):
        SqliteSessionSource("x.db", host_id="h", cli="agy", query=QUERY)


def test_register_mapper_roundtrip():
    register_mapper("_test_cli", _map)
    assert "_test_cli" in known_mappers()


def test_bad_mapper_shape_fails_open(tmp_path):
    db = tmp_path / "c.db"
    _make_db(db, [(TS, "PreToolUse", "s1"), (TS, "Stop", "s1")])
    src = SqliteSessionSource(db, host_id="h1", cli="claude", query=QUERY,
                              mapper=lambda row: ("only", "two"))  # wrong arity
    assert src.poll() == []          # no crash — bad tuples skipped


def test_mapper_raising_fails_open(tmp_path):
    db = tmp_path / "c.db"
    _make_db(db, [(TS, "PreToolUse", "s1")])
    def boom(row):
        raise RuntimeError("mapper blew up")
    src = SqliteSessionSource(db, host_id="h1", cli="claude", query=QUERY, mapper=boom)
    assert src.poll() == []          # exception never escapes poll()
