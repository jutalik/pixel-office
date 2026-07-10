"""Company Layer Phase 5 — HR (staged, reversible, evidence-based)."""
import pytest

from pixel_office.company import hr
from pixel_office.company.employee import Employee, Team
from pixel_office.company.learning import EmployeeMemory
from pixel_office.company.mode import preset


def _team_and_mem():
    t = Team()
    t.hire(Employee("weak", "backend engineer"))
    t.hire(Employee("strong", "backend engineer"))
    mems = {"weak": EmployeeMemory("weak"), "strong": EmployeeMemory("strong")}
    for _ in range(5):                       # weak fails most backend work
        mems["weak"].record("task_blocked", "backend", ok=False)
    for _ in range(5):                       # strong succeeds
        mems["strong"].record("task_done", "backend", ok=True)
    return t, mems


def test_fire_recommendation_from_low_competency():
    t, mems = _team_and_mem()
    recs = hr.review(t, mems, mode=preset("Autopilot"))
    fires = [r for r in recs if r.kind == "fire"]
    assert len(fires) == 1 and fires[0].target == "weak"
    assert fires[0].needs_ceo is True        # termination is a one-way door → always CEO


def test_no_fire_without_enough_evidence():
    t = Team(); t.hire(Employee("new", "writer"))
    mems = {"new": EmployeeMemory("new")}
    mems["new"].record("task_blocked", "writing", ok=False)   # only 1 sample
    assert [r for r in hr.review(t, mems) if r.kind == "fire"] == []


def test_hire_gap_when_no_competent_owner():
    t = Team(); t.hire(Employee("e", "generalist"))
    mems = {"e": EmployeeMemory("e")}
    for _ in range(4):
        mems["e"].record("task_blocked", "design", ok=False)  # team keeps failing design
    hires = [r for r in hr.review(t, mems) if r.kind == "hire"]
    assert hires and hires[0].target == "design"


def test_former_employee_memory_ignored():
    # a departed strong performer's memory must not suppress a real current gap
    t = Team(); t.hire(Employee("cur", "generalist"))
    mems = {
        "cur": EmployeeMemory("cur"),
        "gone": EmployeeMemory("gone"),   # not on the team anymore
    }
    for _ in range(4):
        mems["cur"].record("task_blocked", "design", ok=False)
    for _ in range(5):
        mems["gone"].record("task_done", "design", ok=True)   # stale competence
    hires = [r for r in hr.review(t, mems) if r.kind == "hire"]
    assert hires and hires[0].target == "design"   # gap still flagged


def test_terminate_requires_ceo_and_is_permanent():
    t = Team(); t.hire(Employee("x", "role"))
    with pytest.raises(PermissionError):
        hr.terminate(t, "x", ceo_approved=False)      # one-way door refused
    assert len(t) == 1                                 # still there (reversible so far)
    assert hr.terminate(t, "x", ceo_approved=True) == "terminated x"
    assert t.get("x") is None
