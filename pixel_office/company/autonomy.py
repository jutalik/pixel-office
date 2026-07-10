"""Autonomy loop — the company runs itself toward the goal (docs/COMPANY-LAYER.md).

A bounded tick that: plans work toward stalled KRs, dispatches backlog tasks to
their owners (employees animate + learn), and on cadence runs a review (a
decision memo that escalates per the operating mode), scans trends, and does an
HR review. Driven by an injected clock so it is deterministic + e2e-testable at
zero tokens (employee reasoning is the runtime's pluggable executor).

Bounded per tick (max_dispatch) so cost scales with decisions, not wall-clock.
The operating mode only affects how much reaches the CEO — employees are never
throttled (per the CEO's "no limits").
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable, List, Optional

from .company import Company
from .memo import DecisionMemo
from .runtime import Task


@dataclass
class TickReport:
    planned: int = 0
    dispatched: int = 0
    reviewed: bool = False
    scanned: bool = False
    hr_recs: list = field(default_factory=list)
    ceo_pending: int = 0


# planner(company, kr) -> a Task advancing that Key Result
PlannerFn = Callable[[Company, object], Task]


def default_planner(company: Company, kr) -> Task:
    # assign to the first employee (real routing/skills matching is future work);
    # task_class = the KR id so competency accrues per work-stream
    owner = company.team.all()[0].id if len(company.team) else "unassigned"
    return Task(title=f"advance KR: {kr.text}", dri=owner, task_class=kr.id)


def _due(last: Optional[float], now: float, every: float) -> bool:
    return last is None or (now - last) >= every


class AutonomyLoop:
    def __init__(self, company: Company, *, planner_fn: Optional[PlannerFn] = None,
                 max_dispatch: int = 3, review_every_s: float = 3600,
                 radar_every_s: float = 6 * 3600, hr_every_s: float = 12 * 3600):
        self.company = company
        self.planner_fn = planner_fn or default_planner
        self.max_dispatch = max_dispatch
        self.review_every_s = review_every_s
        self.radar_every_s = radar_every_s
        self.hr_every_s = hr_every_s
        self._last_review: Optional[float] = None
        self._last_radar: Optional[float] = None
        self._last_hr: Optional[float] = None

    def tick(self, now: float) -> TickReport:
        c = self.company
        r = TickReport()
        with c._lock:   # serialize company mutations vs /api/company reads
            # 1. plan (BOUNDED): at most max_dispatch tasks toward stalled KRs
            if not c.backlog and len(c.team):
                for kr in c.okrs.stalled()[:self.max_dispatch]:
                    try:
                        c.backlog.append(self.planner_fn(c, kr))
                        r.planned += 1
                    except Exception:
                        pass   # a bad planner never wedges the loop
                if r.planned:
                    c.record_activity("plan", f"planned {r.planned} task(s) toward the goal")
            # 2. dispatch a bounded number (employees animate + learn)
            while c.backlog and r.dispatched < self.max_dispatch:
                task = c.backlog.pop(0)
                try:
                    result = c.runtime.assign(task)
                    r.dispatched += 1
                    # honest: only call it work when it actually succeeded
                    if getattr(result, "ok", False):
                        c.record_activity("work", f"{task.dri} → {task.title}")
                    else:
                        c.record_activity("blocked", f"{task.dri} blocked on {task.title}")
                except Exception:
                    pass   # a bad task is dropped, not fatal
            # 3-5 each INDEPENDENTLY fail-open so one failure can't abort the rest
            if _due(self._last_review, now, self.review_every_s):
                self._last_review = now
                try:
                    for kr in c.okrs.stalled(threshold=0.05):
                        m = c.memos.open(DecisionMemo(
                            title=f"KR stalled: {kr.text}",
                            dri=(c.team.all()[0].id if len(c.team) else "?"),
                            decision="reprioritize toward this KR",
                            rationale=f"advances: {c.okrs.objective}", reversible=True, risk="medium"))
                        c.memos.decide(m)
                        escalated = any(x is m for x in c.memos.ceo_queue())
                        gate = " → your sign-off" if escalated else " (auto)"
                        c.record_activity("decision", f"reviewed stalled goal: {kr.text}{gate}")
                        break   # one review memo per tick — bounded
                    r.reviewed = True
                except Exception:
                    pass
            if _due(self._last_radar, now, self.radar_every_s):
                self._last_radar = now
                try:
                    trends = c.scan_trends(now)
                    r.scanned = True
                    if trends:
                        c.record_activity("trend", f"scanned trends — {len(trends)} on the radar")
                except Exception:
                    pass
            if _due(self._last_hr, now, self.hr_every_s):
                self._last_hr = now
                try:
                    r.hr_recs = c.hr_review()
                    if r.hr_recs:
                        c.record_activity("hr", f"HR review — {len(r.hr_recs)} recommendation(s)")
                except Exception:
                    pass
            r.ceo_pending = len(c.memos.ceo_queue())
        return r
