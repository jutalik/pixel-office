"""Company Layer Phase 2 — approval envelopes, PO cards, Company facade, /api/company."""
import pytest

from pixel_office.company.company import Company
from pixel_office.company.employee import Employee
from pixel_office.company.memo import DecisionMemo
from pixel_office.company.mode import preset
from pixel_office.company.okr import KeyResult
from pixel_office.company.po import decision_card
from pixel_office.company.runtime import Task
from pixel_office.control.envelope import Envelope, EnvelopeStore


# ---- envelopes ---------------------------------------------------------------

def test_envelope_covers_matching_reversible_action():
    store = EnvelopeStore()
    store.approve(Envelope(purpose="ship features", action_class="deploy:staging",
                           environment="staging", max_cost_usd=10))
    env = store.covers(purpose="ship features", action_class="deploy:staging", environment="staging",
                       cost_usd=2, one_way_door=False, now=0)
    assert env is not None
    assert store.charge(env, 2, now=0) is True
    # an envelope approved for one purpose can't be spent on another
    assert store.covers(purpose="something else", action_class="deploy:staging",
                        environment="staging", cost_usd=1, one_way_door=False, now=0) is None


def test_envelope_rejects_nonfinite_cost():
    import pytest as _pt
    store = EnvelopeStore()
    e = store.approve(Envelope(purpose="x", action_class="spend", max_cost_usd=5))
    assert store.covers(purpose="x", action_class="spend", environment="any",
                        cost_usd=float("nan"), one_way_door=False, now=0) is None
    with _pt.raises(ValueError):
        store.charge(e, float("nan"), now=0)


def test_envelope_never_covers_one_way_door():
    store = EnvelopeStore()
    store.approve(Envelope(purpose="x", action_class="deploy:prod", max_cost_usd=100))
    assert store.covers(purpose="x", action_class="deploy:prod", environment="any",
                        cost_usd=0, one_way_door=True, now=0) is None


def test_envelope_expiry_and_budget_and_revoke():
    store = EnvelopeStore()
    e = store.approve(Envelope(purpose="x", action_class="spend", max_cost_usd=5, expires_at=100))
    assert store.covers(purpose="x", action_class="spend", environment="any", cost_usd=6, one_way_door=False, now=0) is None  # over budget
    assert store.covers(purpose="x", action_class="spend", environment="any", cost_usd=1, one_way_door=False, now=200) is None  # expired
    assert store.covers(purpose="x", action_class="spend", environment="any", cost_usd=1, one_way_door=False, now=0) is e
    store.revoke(e.id)
    assert store.covers(purpose="x", action_class="spend", environment="any", cost_usd=1, one_way_door=False, now=0) is None


# ---- PO decision card --------------------------------------------------------

def test_decision_card_5w1h():
    m = DecisionMemo("delete prod DB", dri="infra", decision="drop table",
                     rationale="clears corrupt data", reversible=False, risk="high")
    c = decision_card(m, objective="be reliable")
    assert c["one_way_door"] is True and c["who"] == "infra"
    assert c["why"] == "clears corrupt data" and "irreversible" in c["how"]
    assert c["recommendation"] == "drop table"


# ---- Company facade ----------------------------------------------------------

def _company(mode="Copilot"):
    c = Company("recipeco", "Become the #1 recipe blog", mode=preset(mode))
    c.team.hire(Employee("eng", "backend engineer"))
    c.team.hire(Employee("writer", "content writer"))
    c.okrs.add_kr(KeyResult("kr1", "weekly posts", target=10, cadence="weekly"))
    c.okrs.update("kr1", 4)
    return c


def test_company_summary_and_views():
    c = _company()
    s = c.summary()
    assert s["headcount"] == 2 and s["objective"].startswith("Become")
    assert s["okr_progress"] == 0.4 and s["mode"]["drive"] == "Copilot"
    assert c.okr_view()[0]["progress"] == 0.4


def test_company_ceo_cards_from_escalated_memos():
    c = _company()
    m = c.memos.open(DecisionMemo("launch to prod", dri="eng", decision="deploy", reversible=False))
    c.memos.decide(m)                       # one-way door → needs CEO
    cards = c.ceo_cards()
    assert len(cards) == 1 and cards[0]["decision"] == "launch to prod"
    assert c.summary()["ceo_pending"] == 1


def test_company_runtime_dispatches():
    c = _company()
    r = c.runtime.assign(Task("write post", dri="writer"))
    assert r.ok


def test_company_hold_meeting_updates_okrs_and_records():
    from pixel_office.company.meeting import GoalUpdate, Outcome
    c = _company()
    events = []
    c.runtime.sink = events.append
    out = c.hold_meeting(
        "weekly review", "how to lift weekly posts?", ["eng", "writer"],
        position_fn=lambda a, p: f"{a}: publish more",
        synthesize_fn=lambda pos, pk: Outcome(decisions=["publish 8/wk"],
                                              goal_updates=[GoalUpdate("kr1", 8)]))
    assert out.decisions == ["publish 8/wk"]
    assert c.okrs.key_results[0].current == 8            # OKR auto-updated by the meeting
    mv = c.meeting_view()
    assert mv["attendees"] == ["eng", "writer"] and mv["decisions"] == ["publish 8/wk"]
    assert c.summary()["has_meeting"] is True
    # attendees animated via the runtime sink (Working → Done, honest stages)
    kinds = [e.kind for e in events]
    assert kinds.count("Working") == 2 and kinds.count("Done") == 2


def test_company_hold_meeting_with_bad_synthesis_still_records():
    c = _company()
    out = c.hold_meeting("x", "y", ["eng"], position_fn=lambda a, p: "ok",
                         synthesize_fn=lambda pos, p: None)   # malformed synthesis
    assert "deferred" in out.decisions[0]
    assert c.meeting_view() is not None                      # recorded, no crash


def test_company_hr_and_trends_views():
    c = _company()
    assert isinstance(c.hr_view(), list) and isinstance(c.trends_view(), list)
    c.radar.search_fn = lambda q: ["AI kitchens", "meal prep"]
    c.scan_trends(now=0)
    assert "AI kitchens" in c.trends_view()


# ---- e2e: a running company lights up the CEO panel via /api/company ----------

def test_e2e_api_company_and_no_company_204():
    pytest.importorskip("fastapi")
    from fastapi.testclient import TestClient

    from pixel_office.server import create_app

    # no company → 204 (UI keeps its "Requires Company Layer" gates)
    with TestClient(create_app(sources=[])) as client:
        assert client.get("/api/company").status_code == 204

    # with a company → real OKRs + a pending CEO card
    c = _company("Copilot")
    m = c.memos.open(DecisionMemo("delete staging", dri="eng", decision="drop", reversible=False))
    c.memos.decide(m)
    app = create_app(sources=[], company=c)
    with TestClient(app) as client:
        data = client.get("/api/company").json()
        assert data["summary"]["okr_progress"] == 0.4
        assert data["okrs"][0]["text"] == "weekly posts"
        assert len(data["ceo_cards"]) == 1 and data["ceo_cards"][0]["one_way_door"] is True
