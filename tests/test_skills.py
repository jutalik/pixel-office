from pixel_office.company import skills
from pixel_office.company.learning import EmployeeMemory, MIN_SAMPLES


def test_every_skill_has_a_valid_family_and_tier():
    assert skills.SKILLS
    for s in skills.SKILLS.values():
        assert s.family in skills.FAMILIES, s.id
        assert s.tier_hint in skills.TIERS, s.id
        assert s.keywords, s.id


def test_get_and_keywords_union():
    assert skills.get("backend-impl").family == "engineering"
    assert skills.get("nope") is None
    kw = skills.keywords_for(["backend-impl", "seo", "unknown-id"])
    assert "backend" in kw and "seo" in kw          # unknown id skipped, no crash


def test_task_class_for_compound_and_bare():
    assert skills.task_class_for("backend-impl", "kr1") == "kr1:backend-impl"
    assert skills.task_class_for("backend-impl") == "backend-impl"
    # never collides with the default planner's bare kr id
    assert skills.task_class_for("backend-impl", "kr1") != "kr1"


def test_proficiency_is_evidence_based_never_invented():
    mem = EmployeeMemory("e1")
    tc = skills.task_class_for("backend-impl", "kr1")
    # below the sample floor → None ("insufficient evidence"), never a number
    for _ in range(MIN_SAMPLES - 1):
        mem.record("task_done", tc, True)
    assert skills.proficiency(mem, "backend-impl", "kr1") is None
    mem.record("task_done", tc, True)                 # now at the floor
    p = skills.proficiency(mem, "backend-impl", "kr1")
    assert p is not None and 0.0 <= p <= 1.0
    assert skills.proficiency(None, "backend-impl") is None


def test_aggregate_proficiency_spans_workstreams_or_none():
    mem = EmployeeMemory("e1")
    assert skills.aggregate_proficiency(mem, "backend-impl") is None   # no evidence
    for kr in ("kr1", "kr2"):
        for _ in range(MIN_SAMPLES):
            mem.record("task_done", skills.task_class_for("backend-impl", kr), True)
    agg = skills.aggregate_proficiency(mem, "backend-impl")
    assert agg is not None and 0.0 <= agg <= 1.0
