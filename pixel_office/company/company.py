"""Company — the facade that bundles the layer for one project.

Ties together the operating mode, the team, the OKR tree, the decision memos, and
the org runtime. Exposes a small summary + the CEO's card queue for the dashboard.
"""
from __future__ import annotations

from typing import Optional

from . import po
from .employee import Team
from .memo import MemoBook
from .mode import OperatingMode
from .okr import OKRTree
from .runtime import OrgRuntime


class Company:
    def __init__(self, name: str, objective: str, *, mode: Optional[OperatingMode] = None,
                 host_id: str = "local", sink=None):
        self.name = name
        self.mode = mode or OperatingMode()
        self.team = Team()
        self.okrs = OKRTree(objective=objective)
        self.memos = MemoBook(self.mode)
        self.runtime = OrgRuntime(self.team, host_id=host_id, company_id=name, sink=sink)

    def summary(self) -> dict:
        return {
            "name": self.name,
            "objective": self.okrs.objective,
            "mode": self.mode.to_dict(),
            "headcount": len(self.team),
            "okr_progress": round(self.okrs.progress(), 3),
            "weekly_progress": round(self.okrs.progress("weekly"), 3),
            "monthly_progress": round(self.okrs.progress("monthly"), 3),
            "ceo_pending": len(self.memos.ceo_queue()),
        }

    def okr_view(self) -> list:
        return [{"id": k.id, "text": k.text, "cadence": k.cadence,
                 "progress": round(k.progress, 3), "current": k.current, "target": k.target}
                for k in self.okrs.key_results]

    def ceo_cards(self) -> list:
        return [po.decision_card(m, objective=self.okrs.objective) for m in self.memos.ceo_queue()]
