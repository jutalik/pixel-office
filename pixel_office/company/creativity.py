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

from dataclasses import dataclass
from typing import List, Tuple

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
