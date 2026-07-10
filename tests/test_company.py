"""Company Layer Phase 1 — OKR tree, decision memos, org runtime, e2e to avatars."""
from datetime import datetime, timezone

import pytest

from pixel_office.company.employee import Employee, Team
from pixel_office.company.memo import DecisionMemo, MemoBook
from pixel_office.company.mode import preset
from pixel_office.company.okr import KeyResult, OKRTree
from pixel_office.company.runtime import OrgRuntime, Task
from pixel_office.telemetry.normalize import normalize
from pixel_office.telemetry.reducer import reduce_all, view


# ---- OKR tree -----------------------------------------------------------------

def test_okr_progress_and_rollup():
    t = OKRTree(objective="Become the #1 recipe blog")
    t.add_kr(KeyResult("kr1", "weekly published posts", target=10, cadence="weekly"))
    t.add_kr(KeyResult("kr2", "subscribers", target=1000, cadence="monthly", metric="subscriber"))
    t.update("kr1", 5)
    assert t.key_results[0].progress == 0.5
    assert t.progress("weekly") == 0.5
    assert 0 < t.progress() < 1


def test_okr_apply_metrics_from_kpi_surface():
    t = OKRTree(objective="grow")
    t.add_kr(KeyResult("s", "subs", target=100, metric="subscriber"))
    n = t.apply_metrics({"subscribers": 40, "requests": 999})   # matches by keyword
    assert n == 1 and t.key_results[0].current == 40


def test_okr_stalled_and_dupes():
    t = OKRTree(objective="x")
    t.add_kr(KeyResult("a", "a", target=10))
    assert t.stalled() and t.stalled()[0].id == "a"
    with pytest.raises(ValueError):
        t.add_kr(KeyResult("a", "dup", target=1))


# ---- decision memos: escalate by operating mode -------------------------------

def test_reversible_memo_auto_decides_in_autopilot():
    book = MemoBook(mode=preset("Autopilot"))
    m = book.open(DecisionMemo("tweak copy", dri="e1", decision="reword", reversible=True, risk="high"))
    assert book.decide(m) == "decided"          # reversible → just happens, even high-risk
    assert not book.ceo_queue()


def test_one_way_door_always_escalates():
    for mode in ("Manual", "Copilot", "Autopilot"):
        book = MemoBook(mode=preset(mode))
        m = book.open(DecisionMemo("delete prod db", dri="e1", decision="drop", reversible=False))
        assert book.decide(m) == "needs_ceo"
        assert book.ceo_queue() == [m]
        assert book.confirm(m, approved=True) == "executed"


def test_copilot_escalates_only_high_risk_reversible():
    book = MemoBook(mode=preset("Copilot"))
    lo = book.open(DecisionMemo("small refactor", dri="e1", decision="x", reversible=True, risk="low"))
    hi = book.open(DecisionMemo("public launch post", dri="e1", decision="y", reversible=True, risk="high"))
    assert book.decide(lo) == "decided"
    assert book.decide(hi) == "needs_ceo"


# ---- team + runtime -----------------------------------------------------------

def _team():
    t = Team()
    t.hire(Employee("eng", "backend engineer", tier="standard"))
    t.hire(Employee("writer", "content writer", tier="cheap"))
    return t


def test_team_hire_and_validate():
    t = _team()
    assert len(t) == 2 and t.get("eng").title == "backend engineer"
    with pytest.raises(ValueError):
        t.hire(Employee("eng", "dup"))
    with pytest.raises(ValueError):
        Employee("x", "t", tier="galaxy").validate()


def test_runtime_dispatch_returns_result_and_is_zero_token():
    rt = OrgRuntime(_team())          # deterministic executor — no model calls
    r = rt.assign(Task("write the launch post", dri="writer"))
    assert r.ok and r.employee_id == "writer" and "content writer" in r.summary


def test_runtime_unknown_dri_raises():
    with pytest.raises(KeyError):
        OrgRuntime(_team()).assign(Task("x", dri="ghost"))


def test_runtime_executor_error_is_blocked_not_raised():
    def boom(emp, task):
        raise RuntimeError("nope")
    rt = OrgRuntime(_team(), executor=boom)
    r = rt.assign(Task("hard", dri="eng"))
    assert r.ok is False and "error" in r.summary


def test_runtime_malformed_executor_result_is_blocked():
    events = []
    rt = OrgRuntime(_team(), sink=events.append, executor=lambda e, t: None)  # returns None
    r = rt.assign(Task("x", dri="eng"))
    assert r.ok is False and [e.kind for e in events] == ["Working", "Blocked"]


def test_okr_rejects_nonfinite():
    t = OKRTree(objective="x")
    t.add_kr(KeyResult("a", "a", target=10))
    with pytest.raises(ValueError):
        t.update("a", float("nan"))
    # a nan that somehow lands on a KR still yields 0 progress, never done
    t.key_results[0].current = float("inf")
    assert t.key_results[0].progress == 0.0 and t.key_results[0].done is False
    assert t.apply_metrics({"a": float("nan")}) == 0   # non-finite metric ignored


# ---- e2e: a company task drives a real avatar through the reducer --------------

def test_company_kinds_normalize():
    assert normalize("company", "Working") == "working"
    assert normalize("company", "Done") == "done"
    assert normalize("company", "Blocked") == "blocked"


def test_e2e_task_animates_employee_avatar():
    events = []
    rt = OrgRuntime(_team(), sink=events.append)   # sink collects RawEvents
    rt.assign(Task("ship it", dri="eng"))
    assert [e.kind for e in events] == ["Working", "Done"]
    # feed the SAME telemetry pipeline the CLI agents use → employee is an avatar
    state = reduce_all(events)
    rows = view(state, datetime(2026, 7, 10, 0, 0, 1, tzinfo=timezone.utc))
    row = next(r for r in rows if r["agent_id"] == "eng")
    assert row["cli"] == "company" and row["activity"] == "done"


def test_e2e_company_avatar_in_live_server():
    pytest.importorskip("fastapi")
    from fastapi.testclient import TestClient

    from pixel_office.server import create_app
    app = create_app(sources=[])
    hub = app.state.hub
    rt = OrgRuntime(_team(), sink=hub.ingest)     # runtime feeds the live dashboard hub
    with TestClient(app) as client:
        rt.assign(Task("ship it", dri="eng"))
        rows = client.get("/api/office").json()["rows"]
        emp = [r for r in rows if r["cli"] == "company" and r["agent_id"] == "eng"]
        assert emp and emp[0]["activity"] == "done"   # employee is a live avatar


def test_e2e_blocked_task_shows_blocked_avatar():
    events = []
    def boom(emp, task):
        raise RuntimeError("x")
    rt = OrgRuntime(_team(), sink=events.append, executor=boom)
    rt.assign(Task("hard", dri="eng"))
    assert [e.kind for e in events] == ["Working", "Blocked"]
    state = reduce_all(events)
    row = view(state, datetime(2026, 7, 10, 0, 0, 1, tzinfo=timezone.utc))[0]
    assert row["activity"] == "blocked"
