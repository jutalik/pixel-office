import json

from pixel_office.telemetry.tailer import TranscriptTailer
from pixel_office.telemetry.watcher import SessionWatcher

TS = "2026-07-10T00:00:01.000Z"


def _line(sess="s1", content="hello"):
    return json.dumps({"type": "user", "timestamp": TS, "sessionId": sess,
                       "message": {"role": "user", "content": content}}) + "\n"


def _watcher(tmp_path, **kw):
    (tmp_path / "state").mkdir(exist_ok=True)
    return SessionWatcher(str(tmp_path / "sessions" / "*.jsonl"), host_id="h1",
                          state_dir=tmp_path / "state", **kw)


def _sessions_dir(tmp_path):
    d = tmp_path / "sessions"
    d.mkdir(exist_ok=True)
    return d


def test_watches_multiple_sessions(tmp_path):
    d = _sessions_dir(tmp_path)
    (d / "a.jsonl").write_text(_line("sess-a"))
    (d / "b.jsonl").write_text(_line("sess-b"))
    events = _watcher(tmp_path).poll()
    assert {e.session_id for e in events} == {"sess-a", "sess-b"}


def test_new_file_picked_up_on_rescan(tmp_path):
    d = _sessions_dir(tmp_path)
    (d / "a.jsonl").write_text(_line("sess-a"))
    w = _watcher(tmp_path)
    assert len(w.poll()) == 1
    (d / "b.jsonl").write_text(_line("sess-b"))
    w._last_rescan = 0  # force the rescan window
    assert {e.session_id for e in w.poll()} == {"sess-b"}


def test_restart_neither_reemits_nor_breaks_forward_seq(tmp_path):
    d = _sessions_dir(tmp_path)
    f = d / "a.jsonl"
    f.write_text(_line("sess-a"))
    w1 = _watcher(tmp_path)
    first = w1.poll()
    assert len(first) == 1
    w1.close()  # persist durable cursors

    w2 = _watcher(tmp_path)  # simulated restart
    assert w2.poll() == []   # exit criterion: no duplicate emission
    with open(f, "a") as fh:
        fh.write(_line("sess-a", "more"))
    again = w2.poll()
    assert len(again) == 1
    assert again[0].seq > first[0].seq  # forward-only across restarts


def test_corrupt_state_file_fails_open(tmp_path):
    d = _sessions_dir(tmp_path)
    (d / "a.jsonl").write_text(_line("sess-a"))
    w1 = _watcher(tmp_path)
    w1.poll()
    w1.close()
    sf = next((tmp_path / "state").glob("watch-*.json"))
    sf.write_text("{corrupt")
    w2 = _watcher(tmp_path)
    assert len(w2.poll()) == 1  # re-reads rather than crashing


def test_max_files_backpressure(tmp_path):
    d = _sessions_dir(tmp_path)
    for i in range(5):
        (d / f"f{i}.jsonl").write_text(_line(f"sess-{i}"))
    w = _watcher(tmp_path, max_files=2)
    events = w.poll()
    assert len({e.session_id for e in events}) == 2
    assert len(w.tailers) == 2


def test_read_cap_digests_large_file_across_polls(tmp_path):
    d = _sessions_dir(tmp_path)
    f = d / "big.jsonl"
    f.write_text(_line("sess-big") * 2000)
    tailer = TranscriptTailer(f, host_id="h1")
    tailer.MAX_READ_BYTES = 4096  # force chunked digestion
    total = 0
    for _ in range(200):
        batch = tailer.poll()
        if not batch and total:
            break
        total += len(batch)
    assert total == 2000  # every record eventually consumed, none duplicated
