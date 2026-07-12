from pixel_office.company import skills, workflows


class _KR:
    def __init__(self, text="", metric=""):
        self.text, self.metric = text, metric


def test_catalog_present_and_steps_reference_valid_skills():
    assert len(workflows.WORKFLOWS) >= 5
    for w in workflows.WORKFLOWS.values():
        assert w.steps
        for st in w.steps:
            assert st.name
            if st.skill:
                assert st.skill in skills.SKILLS, (w.id, st.name, st.skill)
            if st.family:
                assert st.family in skills.FAMILIES, (w.id, st.name, st.family)
            assert st.skill or st.family, (w.id, st.name)   # a step must route somewhere


def test_ship_feature_is_the_canonical_engineering_flow():
    wf = workflows.get("ship-feature")
    names = [s.name for s in wf.steps]
    assert names[0] == "spec" and names[-1] == "deploy"
    assert "implement" in names and "test" in names and "review" in names


def test_for_kr_matches_by_family_and_declines_ambiguity():
    assert workflows.for_kr(_KR("ship 5 backend features")) == "ship-feature"
    assert workflows.for_kr(_KR("publish 10 blog articles")) == "content-pipeline"
    assert workflows.for_kr(_KR("reduce churn among subscribers")) == "growth-experiment"
    # nothing measurable/matchable → None (caller falls back to the plain planner)
    assert workflows.for_kr(_KR("")) is None
    assert workflows.for_kr(_KR("xyzzy qwerty")) is None


def test_for_kr_special_triggers_win_over_family():
    assert workflows.for_kr(_KR("resolve the production outage")) == "incident-response"
    assert workflows.for_kr(_KR("rearchitect for tradeoffs")) == "architecture-review"
    # a special trigger beats a competing family word (backend/feature = engineering)
    assert workflows.for_kr(_KR("outage in the backend feature")) == "incident-response"
