"""Company — the facade that bundles the layer for one project.

Ties together the operating mode, the team, the OKR tree, the decision memos, and
the org runtime. Exposes a small summary + the CEO's card queue for the dashboard.
"""
from __future__ import annotations

from typing import Optional

from . import hr as hr_mod
from . import po
from .employee import Team
from .memo import MemoBook
from .meeting import Meeting, apply_outcome
from .mode import OperatingMode
from .okr import OKRTree
from .radar import TrendRadar
from .runtime import OrgRuntime


class Company:
    def __init__(self, name: str, objective: str, *, mode: Optional[OperatingMode] = None,
                 host_id: str = "local", sink=None, niche: str = "", search_fn=None):
        self.name = name
        self.mode = mode or OperatingMode()
        self.team = Team()
        self.okrs = OKRTree(objective=objective)
        self.memos = MemoBook(self.mode)
        self.runtime = OrgRuntime(self.team, host_id=host_id, company_id=name, sink=sink)
        self.radar = TrendRadar(objective=objective, niche=niche, search_fn=search_fn)
        self._trends: list = []
        self._last_meeting: Optional[dict] = None

    def hold_meeting(self, topic: str, decision_to_make: str, attendees, *,
                     position_fn, synthesize_fn, packet: Optional[dict] = None):
        """Run an async meeting (parallel memos → one synthesis); attendees animate
        via the runtime sink, the outcome auto-updates OKRs, and it's recorded for
        the office meeting room (honest: a concluded workflow, not live dialogue)."""
        m = Meeting(topic, decision_to_make, [str(a) for a in attendees], packet=packet or {})
        outcome = m.run(position_fn=position_fn, synthesize_fn=synthesize_fn,
                        sink=lambda emp, stage: self.runtime._emit(emp, stage))
        apply_outcome(self.okrs, outcome)
        self._last_meeting = {"topic": topic, "attendees": m.attendees,
                              "decisions": outcome.decisions,
                              "actions": outcome.actions}
        return outcome

    def meeting_view(self) -> Optional[dict]:
        return self._last_meeting

    def hr_review(self) -> list:
        return hr_mod.review(self.team, self.runtime.memories, mode=self.mode)

    def scan_trends(self, now: float) -> list:
        rep = self.radar.scan(now)
        if rep.ran and rep.trends:
            self._trends = rep.trends
        return self._trends

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
            "hr_flags": sum(1 for r in self.hr_review() if r.needs_ceo),
            "trends": len(self._trends),
            "has_meeting": self._last_meeting is not None,
        }

    def hr_view(self) -> list:
        return [{"kind": r.kind, "target": r.target, "reason": r.reason,
                 "needs_ceo": r.needs_ceo} for r in self.hr_review()]

    def trends_view(self) -> list:
        return list(self._trends)

    def okr_view(self) -> list:
        return [{"id": k.id, "text": k.text, "cadence": k.cadence,
                 "progress": round(k.progress, 3), "current": k.current, "target": k.target}
                for k in self.okrs.key_results]

    def ceo_cards(self) -> list:
        return [po.decision_card(m, objective=self.okrs.objective) for m in self.memos.ceo_queue()]
