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

from . import creativity, roles as _roles, skills, workflows
from .company import Company
from .memo import DecisionMemo
from .routing import best_owner, best_owner_for_step
from .runtime import Task


@dataclass
class TickReport:
    planned: int = 0
    dispatched: int = 0
    reviewed: bool = False
    scanned: bool = False
    hr_recs: list = field(default_factory=list)
    ceo_pending: int = 0
    initiatives: int = 0


# planner(company, kr) -> a Task advancing that Key Result
PlannerFn = Callable[[Company, object], Task]


def default_planner(company: Company, kr) -> Task:
    # route by role fit + proven competency (routing.best_owner), not always the
    # first hire; task_class = the KR id so competency accrues per work-stream
    owner = best_owner(company, kr)
    return Task(title=f"advance KR: {kr.text}",
                dri=owner.id if owner else "unassigned", task_class=kr.id)


class _NoWork(Exception):
    """'This workflow has nothing to dispatch this tick' — swallowed by the plan
    loop's try/except, so no task is enqueued (never fabricate work)."""


def workflow_planner(company: Company, kr) -> Task:
    """Opt-in planner: drive a KR through its workflow's ordered steps, ONE per tick,
    each routed to the best-skilled employee. Steps gate on the prior step's real
    result (company.advance_workflow). Falls back to default_planner when no workflow
    fits the KR — so it is a strict superset of the default behavior."""
    run = company.workflows.get(str(kr.id))
    if run is None:
        wf_id = workflows.for_kr(kr)
        if wf_id is None:
            return default_planner(company, kr)
        run = company.start_workflow(kr.id, wf_id)
    if run.done or run.blocked:
        raise _NoWork()
    wf = workflows.get(run.workflow_id)
    if wf is None or run.step_index >= len(wf.steps):
        run.done = True
        raise _NoWork()
    step = wf.steps[run.step_index]
    owner = best_owner_for_step(company, kr, step)
    if owner is None:
        raise _NoWork()   # no one to own this step → don't enqueue an unassignable task
    task = Task(title=f"{step.name}: {kr.text}", dri=owner.id,
                task_class=skills.task_class_for(step.skill or step.family, kr.id))
    company.mark_workflow_task(task.id, kr.id)
    return task


def planner_for(company: Company) -> PlannerFn:
    """The workflow planner AUTOMATICALLY when the team carries workflows (built-in
    roles do), else the plain planner. Not a user opt-in — a company with library
    roles ships work via workflows by default."""
    try:
        if any(getattr(e, "workflows", ()) for e in company.team.all()):
            return workflow_planner
    except Exception:
        pass
    return default_planner


def _due(last: Optional[float], now: float, every: float) -> bool:
    return last is None or (now - last) >= every


# deterministic (zero-token) meeting: an honest concluded synthesis, NOT fabricated
# dialogue, and no invented goal updates — real progress lands only from real work.
def _stub_position(emp_id: str, packet: dict) -> str:
    return f"prioritize {packet.get('kr', 'the goal')}"


def _stub_synthesize(positions, packet) -> "object":
    from .meeting import Outcome
    kr = packet.get("kr", "the goal")
    return Outcome(decisions=[f"align the team on: {kr}"],
                   actions=[{"dri": a, "task": f"advance {kr}", "deadline": "this week"}
                            for a in list(positions)[:3]],
                   goal_updates=[])


class AutonomyLoop:
    def __init__(self, company: Company, *, planner_fn: Optional[PlannerFn] = None,
                 max_dispatch: int = 3, review_every_s: float = 3600,
                 radar_every_s: float = 6 * 3600, hr_every_s: float = 12 * 3600,
                 initiative_every_s: float = 6 * 3600):
        self.company = company
        self.planner_fn = planner_fn or default_planner
        self.max_dispatch = max_dispatch
        self.review_every_s = review_every_s
        self.radar_every_s = radar_every_s
        self.hr_every_s = hr_every_s
        self.initiative_every_s = initiative_every_s
        self._last_review: Optional[float] = None
        self._last_radar: Optional[float] = None
        self._last_hr: Optional[float] = None
        self._last_initiative: Optional[float] = None

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
                    c.advance_workflow(task, result)   # advance the KR's workflow a step (no-op for plain tasks)
                    # honest: only call it work when it actually succeeded
                    if getattr(result, "ok", False):
                        c.record_activity("work", f"{task.dri} → {task.title}")
                    else:
                        c.record_activity("blocked", f"{task.dri} blocked on {task.title}")
                except Exception:
                    # assign raised (e.g. a fired/unknown DRI): halt the workflow and
                    # release its task→KR mapping so it can't leak or infinitely retry.
                    try:
                        c.advance_workflow(task, None)
                    except Exception:
                        pass
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
                    # a bounded meeting: gather up to 3 employees on the top stalled KR.
                    # Honest — a concluded synthesis (no fake dialogue, no fabricated goal
                    # updates); attendees animate + surface in the office meeting room.
                    stalled = c.okrs.stalled(threshold=0.05)
                    if stalled and len(c.team) >= 2:
                        attendees = [e.id for e in c.team.all()[:3]]
                        c.hold_meeting(f"stalled: {stalled[0].text}", "reprioritize", attendees,
                                       position_fn=_stub_position, synthesize_fn=_stub_synthesize,
                                       packet={"kr": stalled[0].text})
                        c.record_activity("meeting", f"met on: {stalled[0].text}")
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
            # 6. individual initiative (BOUNDED): a creative employee proposes one idea
            #    toward the goal via divergent lenses. Deterministic + honest — an idea
            #    is a PROPOSAL (its unproven claims are assumptions); reversible/local
            #    ideas auto-become one small exploration task, nothing riskier.
            if _due(self._last_initiative, now, self.initiative_every_s):
                self._last_initiative = now
                try:
                    creatives = [e for e in c.team.all() if _roles.is_creative(e)]
                    if creatives:
                        emp = creatives[int(now) % len(creatives)]   # rotate proposers deterministically
                        ideas = creativity.validate_ideas(creativity.deterministic_ideas(
                            c.okrs.objective, _roles.family_of(emp.role), option_count=3))
                        if ideas:
                            idea = ideas[0]
                            c.record_activity("idea", f"{emp.id} proposed {idea.lens}: {idea.title}")
                            if idea.reversible and len(c.backlog) < self.max_dispatch:
                                c.add_task(f"explore: {idea.title}", emp.id, task_class="initiative")
                            r.initiatives = 1
                except Exception:
                    pass
            r.ceo_pending = len(c.memos.ceo_queue())
        return r
