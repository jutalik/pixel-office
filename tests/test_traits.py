from pixel_office.company.learning import MAX_OBSERVATIONS, EmployeeMemory


def test_top_trait_floor_and_isolation_from_competency():
    m = EmployeeMemory("e")
    m.observe("focus", "api-design")
    assert m.top_trait("focus") is None                 # 1 obs < min_samples(2) → no trait
    m.observe("focus", "api-design")
    assert m.top_trait("focus") == "api-design"
    # a behavioral observation must NOT create competency evidence
    assert m.competency("api-design") is None and m.samples("api-design") == 0


def test_top_trait_tie_break_is_deterministic():
    m = EmployeeMemory("e")
    for v in ("aaa", "zzz", "aaa", "zzz"):              # 2-2 tie
        m.observe("focus", v)
    assert m.top_trait("focus") == "zzz"                # max on (count, value) → alphabetically greater


def test_observations_are_bounded():
    m = EmployeeMemory("e")
    for _ in range(MAX_OBSERVATIONS + 50):
        m.observe("focus", "x")
    assert len(m.observations) <= MAX_OBSERVATIONS      # no unbounded growth on the hot path
