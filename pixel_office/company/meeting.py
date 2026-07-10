"""Meetings — parallel memos → one synthesis, NOT a conversation (docs §4).

A meeting is the exception, admitted only when a real decision blocks ≥2 roles
with genuinely different info and async can't resolve it. It runs as: one shared
evidence packet → each attendee submits ONE position independently (parallel) →
ONE synthesis call → decisions + action items + goal updates. Position/synthesis
are pluggable (LLM in prod, deterministic stubs in tests) so it is fully
e2e-testable at zero tokens. Lifecycle events drive an honest "gathering"
animation (workflow stages, never fake back-and-forth dialogue).
"""
from __future__ import annotations

import itertools
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from typing import Callable, Dict, List, Optional

_ids = itertools.count(1)


def admission_test(*, has_specific_decision: bool, attendee_count: int,
                   delay_cost: float, meeting_cost: float, async_resolvable: bool) -> bool:
    """A meeting is worth its cost only if a specific decision blocks ≥2 roles,
    it can't be resolved async, and delay costs more than the meeting."""
    return (has_specific_decision and attendee_count >= 2
            and delay_cost > meeting_cost and not async_resolvable)


@dataclass
class GoalUpdate:
    kr_id: str
    current: float


@dataclass
class Outcome:
    decisions: List[str] = field(default_factory=list)
    actions: List[dict] = field(default_factory=list)      # {"dri":..., "task":..., "deadline":...}
    goal_updates: List[GoalUpdate] = field(default_factory=list)
    dissent: List[str] = field(default_factory=list)


# position(attendee_id, packet) -> str ; synthesize(positions, packet) -> Outcome
PositionFn = Callable[[str, dict], str]
SynthesizeFn = Callable[[Dict[str, str], dict], Outcome]


@dataclass
class Meeting:
    topic: str
    decision_to_make: str
    attendees: List[str]
    packet: dict = field(default_factory=dict)     # the shared evidence, compiled once
    id: int = field(default_factory=lambda: next(_ids))
    positions: Dict[str, str] = field(default_factory=dict)
    outcome: Optional[Outcome] = None
    status: str = "scheduled"

    def run(self, *, position_fn: PositionFn, synthesize_fn: SynthesizeFn, sink=None) -> Outcome:
        """Drive the meeting to an Outcome. `sink(employee_id, stage)` gets honest
        lifecycle stages (never fabricated dialogue)."""
        def _emit(emp, stage):
            if sink:
                try:
                    sink(emp, stage)
                except Exception:
                    pass
        self.status = "collecting"
        for a in self.attendees:
            _emit(a, "Working")                    # everyone gathers to prepare a memo
        # positions are INDEPENDENT → collect them in PARALLEL (one memo each,
        # from the same evidence packet), never a sequential conversation.
        if self.attendees:
            with ThreadPoolExecutor(max_workers=min(len(self.attendees), 8)) as ex:
                futs = {a: ex.submit(position_fn, a, self.packet) for a in self.attendees}
                for a, f in futs.items():
                    try:
                        self.positions[a] = f.result()
                    except Exception:
                        self.positions[a] = ""     # a missing memo, not a crash
        self.status = "synthesizing"
        try:
            self.outcome = synthesize_fn(self.positions, self.packet)
        except Exception:
            self.outcome = Outcome(decisions=["(synthesis failed — deferred)"])
        if not isinstance(self.outcome, Outcome):   # None / malformed return, not an exception
            self.outcome = Outcome(decisions=["(synthesis returned no valid outcome — deferred)"])
        for a in self.attendees:
            _emit(a, "Done")                        # returns to its room
        self.status = "completed"
        return self.outcome


def apply_outcome(okrs, outcome: Outcome) -> int:
    """Auto-update weekly/monthly KRs from a meeting outcome (the growth loop)."""
    applied = 0
    for gu in outcome.goal_updates:
        try:
            okrs.update(gu.kr_id, gu.current)
            applied += 1
        except (KeyError, ValueError, TypeError):
            pass   # a malformed goal update (bad id / None / non-numeric) is skipped
    return applied
