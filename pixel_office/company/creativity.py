"""Creativity — divergent options via LENSES, honest by design (docs/COMPANY-LAYER.md).

Creative roles (designer / writer / growth) don't get a "correct style"; they get
divergent *lenses*. A deterministic core scaffolds exactly one option per lens
(zero-token, testable); an optional LLM can enrich the wording later. Ideas are
PROPOSALS, not facts — each carries its unproven claims as `assumptions` plus a
reversibility/cost tag, and must pass a validator (one idea per lens, no external
side effects) before it can become work. Lens-splitting (not temperature) is what
keeps the options genuinely different — and it stays deterministic.
"""
from __future__ import annotations

import itertools
from dataclasses import dataclass, field
from typing import List, Optional, Tuple

_idea_ids = itertools.count(1)

# divergent lenses per role family (not a "right answer" — different angles)
LENSES = {
    "design": ("flow", "accessibility", "visual-metaphor"),
    "content": ("reader-pain", "story-angle", "distribution-format"),
    "growth": ("acquisition", "activation", "retention"),
    "engineering": ("simplicity", "reliability", "performance"),
    "data": ("segment", "leading-indicator", "counterfactual"),
}
_FALLBACK = ("smallest-reversible", "local-first")


@dataclass(frozen=True)
class Idea:
    title: str
    lens: str
    rationale: str
    assumptions: Tuple[str, ...] = ()
    reversible: bool = True
    cost: str = "small"


@dataclass
class IdeaRecord:
    """A proposed idea tracked through its lifecycle (see ideas.py). MUTABLE — the
    autonomy loop advances its status only on REAL events (task success, a targeted
    KR rising). Never carries an 'impact' number; only outcome-associated evidence.

    Two assumption lists are kept SEPARATE and honest: `system_assumptions` is the
    always-true epistemic floor (this is unproven), owned by the system; the optional
    `proposer_assumptions` holds ONLY what a live LLM actually returned — never
    synthesized, so nothing fabricated is attributed to the employee."""
    proposer_id: str
    lens: str
    content: str                 # the idea itself (deterministic skeleton, or live LLM text)
    target_kr_id: str            # the KR this idea explicitly aims to move (not guessed)
    reversible: bool = True
    cost: str = "small"
    system_assumptions: Tuple[str, ...] = ()
    proposer_assumptions: Tuple[str, ...] = ()
    # experiment contract — PREREGISTERED at propose time, immutable, so success can
    # never be redefined after the fact (a real hypothesis, not a post-hoc story).
    success_threshold: float = 0.0   # min BASELINE-ADJUSTED delta that counts as a win
    evaluation_window: int = 6       # ticks after delivery to observe the outcome
    status: str = "proposed"
    task_id: Optional[int] = None
    created_tick: int = 0
    delivered_at: int = -1       # tick the pursued task succeeded (snapshot taken then)
    kr_snapshot: float = 0.0     # target KR value AT delivery (post-delivery-tick baseline)
    baseline_rate: float = 0.0   # KR's per-tick trend BEFORE delivery (what it would do anyway)
    baseline_ok: bool = True     # False when no pre-delivery trend could be established → NOT creditable
    contended: bool = False      # this idea ever shared its target KR with another live idea
    raw_delta: float = 0.0       # unadjusted rise since delivery (shown for transparency)
    associated_delta: float = 0.0  # BASELINE-ADJUSTED excess (the part above the prior trend)
    outcome_points: float = 0.0  # earned ONLY on exclusive, threshold-beating association
    settled_at: int = -1
    id: int = field(default_factory=lambda: next(_idea_ids))


@dataclass
class LearningRecord:
    """What a FAILED experiment taught — kept ENTIRELY separate from reputation and KR
    progress. A falsified hypothesis with a reusable scope (which lens on which KR did
    NOT beat baseline), used only as context for future proposals. Never points."""
    proposer_id: str
    lens: str
    target_kr_id: str
    falsified: str        # the assumption that did not hold
    idea_id: int
    tick: int


def learning_from(idea, tick: int) -> "LearningRecord":
    """Distil a FAILED idea into a reusable lesson: the (proposer, lens, KR) scope and
    the specific assumption its miss falsified. Prefers the proposer's own stated
    assumption, else the system floor — never invents one."""
    assumption = (idea.proposer_assumptions or idea.system_assumptions or ("(no stated assumption)",))[0]
    return LearningRecord(proposer_id=idea.proposer_id, lens=idea.lens,
                          target_kr_id=idea.target_kr_id, falsified=str(assumption)[:160],
                          idea_id=idea.id, tick=int(tick))


def new_idea_record(proposer_id: str, lens: str, target_kr_id: str, *,
                    objective: str = "", content: str = "",
                    proposer_assumptions: Tuple[str, ...] = (),
                    reversible: bool = True, cost: str = "small",
                    success_threshold: float = 0.0, evaluation_window: int = 6,
                    created_tick: int = 0) -> IdeaRecord:
    """Build a ledger record with its PREREGISTERED experiment contract. `content` may
    be a live LLM's idea text; when empty a deterministic skeleton is used (0-token
    demo/tests). The system floor assumption is ALWAYS attached (truthful epistemic
    status, not a fabricated claim)."""
    obj = str(objective or "the goal").strip() or "the goal"
    body = " ".join(str(content or "").split())[:280] or \
        f"[{lens}] a small reversible experiment toward {obj}"
    floor = (f"unverified that this {lens} idea moves {target_kr_id or obj} above its baseline",)
    keep = tuple(" ".join(str(a).split())[:160] for a in (proposer_assumptions or ()) if str(a).strip())[:3]
    return IdeaRecord(proposer_id=str(proposer_id), lens=str(lens), content=body,
                      target_kr_id=str(target_kr_id or ""), reversible=bool(reversible),
                      cost=str(cost), system_assumptions=floor, proposer_assumptions=keep,
                      success_threshold=max(0.0, float(success_threshold)),
                      evaluation_window=max(1, int(evaluation_window)),
                      created_tick=int(created_tick))


def split_assumption(text: str) -> Tuple[str, Tuple[str, ...]]:
    """Split a trailing 'Assumption: <x>' line out of a live idea into
    (content, (assumption,)). Only what the CLI ACTUALLY returned is kept — nothing
    is synthesized, so a proposer's assumption is always their own words or absent."""
    t = " ".join(str(text or "").split()).strip()
    low = t.lower()
    idx = low.rfind("assumption:")
    if idx == -1:
        return t, ()
    content = t[:idx].strip().rstrip("-–—.").strip()
    assumption = t[idx + len("assumption:"):].strip()
    return (content or t), ((assumption[:160],) if assumption else ())


def lenses_for(family: str) -> Tuple[str, ...]:
    return LENSES.get(str(family or ""), _FALLBACK)


def deterministic_ideas(objective: str, family: str, *, option_count: int = 3) -> List[Idea]:
    """One scaffold idea per lens — divergent by construction. No fabricated demand
    or metric impact: everything unproven is recorded as an assumption."""
    obj = str(objective or "the goal").strip() or "the goal"
    lenses = lenses_for(family)[:max(1, int(option_count))]
    return [Idea(
        title=f"[{ln}] a small reversible experiment toward {obj}",
        lens=ln,
        rationale=f"probe {obj} through the {ln} lens with a local, reversible trial",
        assumptions=(f"unverified that a {ln} change moves {obj}",),
        reversible=True, cost="small") for ln in lenses]


def validate_ideas(ideas) -> List[Idea]:
    """Honesty gate: keep at most one idea per lens, and drop any idea that states
    no assumptions (a bare fact-claim with no evidence is not an honest proposal)."""
    seen = set()
    out: List[Idea] = []
    for i in ideas or ():
        if not isinstance(i, Idea) or i.lens in seen or not i.assumptions:
            continue
        seen.add(i.lens)
        out.append(i)
    return out
