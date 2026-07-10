"""Decision memos — async decisions with a DRI (docs/COMPANY-LAYER.md §1, §4).

The unit of decision. A memo is written (not discussed), owned by one employee
(DRI), and either just happens (reversible two-way door) or escalates to the CEO
(irreversible one-way door, or risky enough for the operating mode). Deterministic.
"""
from __future__ import annotations

import itertools
from dataclasses import dataclass, field
from typing import List, Optional

from .mode import OperatingMode

_ids = itertools.count(1)

# status lifecycle
DRAFT, DECIDED, NEEDS_CEO, EXECUTED, REJECTED = "draft", "decided", "needs_ceo", "executed", "rejected"


@dataclass
class DecisionMemo:
    title: str
    dri: str                       # the single accountable employee id
    decision: str                  # the recommended action
    rationale: str = ""
    reversible: bool = True         # two-way door (reversible) vs one-way (irreversible)
    risk: str = "low"               # low | medium | high
    id: int = field(default_factory=lambda: next(_ids))
    status: str = DRAFT

    @property
    def one_way_door(self) -> bool:
        return not self.reversible


class MemoBook:
    """Holds open decisions; routes each by the operating mode."""

    def __init__(self, mode: Optional[OperatingMode] = None):
        self.mode = mode or OperatingMode()
        self.memos: List[DecisionMemo] = []

    def open(self, memo: DecisionMemo) -> DecisionMemo:
        self.memos.append(memo)
        return memo

    def decide(self, memo: DecisionMemo) -> str:
        """Move a memo forward: escalate to the CEO if the mode requires it,
        otherwise it is auto-decided (bias for action on reversible calls)."""
        if self.mode.reaches_ceo(one_way_door=memo.one_way_door, risk=memo.risk):
            memo.status = NEEDS_CEO
        else:
            memo.status = DECIDED
        return memo.status

    def ceo_queue(self) -> List[DecisionMemo]:
        return [m for m in self.memos if m.status == NEEDS_CEO]

    def confirm(self, memo: DecisionMemo, approved: bool) -> str:
        if memo.status != NEEDS_CEO:
            raise ValueError("memo is not awaiting the CEO")
        memo.status = EXECUTED if approved else REJECTED
        return memo.status
