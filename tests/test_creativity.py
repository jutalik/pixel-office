from pixel_office.company import creativity
from pixel_office.company.creativity import Idea


def test_deterministic_ideas_are_one_per_lens_and_honest():
    ideas = creativity.deterministic_ideas("1000 signups", "growth", option_count=3)
    assert len(ideas) == 3
    assert [i.lens for i in ideas] == list(creativity.lenses_for("growth"))[:3]
    # honest: every idea's claim is an assumption, reversible, small
    assert all(i.assumptions and i.reversible and i.cost == "small" for i in ideas)


def test_validate_dedupes_lenses_and_requires_assumptions():
    out = creativity.validate_ideas([
        Idea("a", "flow", "r", assumptions=("x",)),
        Idea("b", "flow", "r2", assumptions=("y",)),      # duplicate lens → dropped
        Idea("c", "accessibility", "r3", assumptions=()),  # no assumption → dropped
        Idea("d", "visual-metaphor", "r4", assumptions=("z",)),
    ])
    assert [i.lens for i in out] == ["flow", "visual-metaphor"]


def test_unknown_family_falls_back():
    assert creativity.lenses_for("nope") == creativity._FALLBACK
    assert creativity.validate_ideas([]) == []
