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

from . import creativity, metrics, roles as _roles, skills, workflows
from .company import Company
from .meeting import admission_test
from .memo import DecisionMemo
from .routing import best_owner, best_owner_for_step
from .runtime import Task


def _active_stalled(company: Company, threshold: float = 0.1) -> list:
    """Stalled KRs that still have room to work — EXCLUDING those whose workflow is
    already done. A completed playbook shouldn't keep the loop planning/meeting on
    that KR forever (it waits on real metrics, not more churn)."""
    out = []
    for kr in company.okrs.stalled(threshold):
        run = company.workflows.get(str(kr.id))
        if run is None or not (run.done or run.abandoned):
            out.append(kr)
    return out


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
    if run.done or run.blocked or run.abandoned:
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
                 initiative_every_s: float = 6 * 3600, metrics_every_s: float = 300,
                 meeting_every_s: float = 4 * 3600):
        self.company = company
        self.planner_fn = planner_fn or default_planner
        self.max_dispatch = max_dispatch
        self.review_every_s = review_every_s
        self.radar_every_s = radar_every_s
        self.hr_every_s = hr_every_s
        self.initiative_every_s = initiative_every_s
        self.metrics_every_s = metrics_every_s
        self.meeting_every_s = meeting_every_s
        self._last_review: Optional[float] = None
        self._last_radar: Optional[float] = None
        self._last_hr: Optional[float] = None
        self._last_initiative: Optional[float] = None
        self._last_metrics: Optional[float] = None
        self._last_meeting: Optional[float] = None

    def tick(self, now: float) -> TickReport:
        c = self.company
        r = TickReport()
        # ---- phase A: plan + choose work (under lock — pure state, NO I/O) --------
        # The lock serializes COMPANY state (backlog/okrs/activity/memos/workflows) vs
        # /api/company reads. Per-employee memory is mutated lock-free in phase B (so
        # the CLI can't freeze the dashboard); its readers snapshot before iterating.
        with c._lock:
            # 1. plan (BOUNDED): at most max_dispatch tasks toward stalled KRs
            if not c.backlog and len(c.team):
                for kr in _active_stalled(c)[:self.max_dispatch]:
                    try:
                        c.backlog.append(self.planner_fn(c, kr))
                        r.planned += 1
                    except Exception:
                        pass   # a bad planner never wedges the loop
                if r.planned:
                    c.record_activity("plan", f"planned {r.planned} task(s) toward the goal")
            # 2a. pick a bounded batch to dispatch — but DON'T run the CLI yet
            pending: List[Task] = []
            while c.backlog and len(pending) < self.max_dispatch:
                pending.append(c.backlog.pop(0))
            do_metrics = _due(self._last_metrics, now, self.metrics_every_s)
            if do_metrics:
                self._last_metrics = now
            product_url = getattr(c, "product_url", "")
        # ---- phase B: I/O OUTSIDE the lock (CLI + HTTP) so /api/company stays --------
        #     responsive. Each employee's CLI can take minutes in live; the growth
        #     poll hits the network. Holding the company lock across either would
        #     freeze the dashboard, so we only touch state again in phase C.
        dispatched = []
        for task in pending:
            try:
                dispatched.append((task, c.runtime.assign(task), None))
            except Exception as e:
                dispatched.append((task, None, e))   # e.g. fired/unknown DRI
        fetched = None
        if do_metrics:
            try:
                fetched = metrics.fetch_metrics(product_url)
            except Exception:
                fetched = None
        # ---- phase C: record results + cadence work (under lock — pure state) --------
        with c._lock:
            for task, result, err in dispatched:
                if err is not None:
                    # assign raised (fired/unknown DRI): halt any workflow AND leave an
                    # honest blocked trace so NO task — plain, meeting, or initiative —
                    # ever vanishes without a record.
                    try:
                        c.advance_workflow(task, None)
                    except Exception:
                        pass
                    c.record_activity("blocked", f"{task.dri or '?'} could not start {task.title}")
                    continue
                r.dispatched += 1
                c.advance_workflow(task, result)   # advance the KR's workflow a step (no-op for plain tasks)
                # honest: only call it work when it actually succeeded
                if getattr(result, "ok", False):
                    c.record_activity("work", f"{task.dri} → {task.title}")
                else:
                    c.record_activity("blocked", f"{task.dri} blocked on {task.title}")
            # 3. growth loop: apply the REAL KPI surface polled above → OKRs. Only
            #    advances a KR from a metric it actually names (honest — unset product
            #    url → no poll, OKRs stay at 0% until real metrics land).
            if do_metrics and fetched:
                try:
                    moved = c.okrs.apply_metrics(fetched)
                    if moved:
                        c.record_activity("metric", f"real metrics moved {moved} KR(s)")
                except Exception:
                    pass
            # 4-6 each INDEPENDENTLY fail-open so one failure can't abort the rest
            if _due(self._last_review, now, self.review_every_s):
                self._last_review = now
                try:
                    active = _active_stalled(c, 0.05)
                    if active:
                        kr = active[0]
                        m = c.memos.open(DecisionMemo(
                            title=f"KR stalled: {kr.text}",
                            dri=(c.team.all()[0].id if len(c.team) else "?"),
                            decision="reprioritize toward this KR",
                            rationale=f"advances: {c.okrs.objective}", reversible=True, risk="medium"))
                        c.memos.decide(m)
                        escalated = any(x is m for x in c.memos.ceo_queue())
                        gate = " → your sign-off" if escalated else " (auto)"
                        c.record_activity("decision", f"reviewed stalled goal: {kr.text}{gate}")
                    # review also UN-BLOCKS a halted workflow so it retries next tick
                    for run in list(c.workflows.values()):
                        if run.blocked and c.clear_workflow(run.kr_id):
                            c.record_activity("retry", f"unblocked workflow {run.workflow_id}")
                            break   # one retry per review — bounded
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
            # 7. meeting (cadence, ADMISSION-GATED on REAL evidence): a meeting only
            #    earns its cost when the situation genuinely can't be resolved async —
            #    a blocked workflow, or ≥2 stalled KRs competing for the same team. A
            #    single stalled KR is handled by the review memo (async), not a meeting.
            #    The admission_test inputs are computed from real state, not hard-coded.
            if _due(self._last_meeting, now, self.meeting_every_s):
                self._last_meeting = now
                try:
                    active = _active_stalled(c, 0.05)
                    # a still-live blocked workflow is real evidence; an ABANDONED one
                    # (blocked stays True) is not — it must not admit meetings forever.
                    blocked_wf = any(getattr(run, "blocked", False) and not getattr(run, "abandoned", False)
                                     for run in c.workflows.values())
                    real_blocker = blocked_wf or len(active) >= 2   # needs the room, not a memo
                    if active and admission_test(
                            has_specific_decision=bool(active), attendee_count=len(c.team),
                            delay_cost=(1.0 if real_blocker else 0.2), meeting_cost=0.1 * len(c.team),
                            async_resolvable=not real_blocker):
                        kr = active[0]
                        attendees = [e.id for e in c.team.all()[:3]]
                        outcome = c.hold_meeting(f"stalled: {kr.text}", "reprioritize", attendees,
                                                 position_fn=_stub_position, synthesize_fn=_stub_synthesize,
                                                 packet={"kr": kr.text})
                        c.record_activity("meeting", f"met on: {kr.text}")
                        # action items → bounded REAL backlog work (not display-only),
                        # de-duped so a persistently-stalled KR doesn't re-queue the same
                        # action every cadence (bounded cumulative cost, not just size).
                        pending_titles = {t.title for t in c.backlog}
                        for act in (getattr(outcome, "actions", None) or [])[:self.max_dispatch]:
                            dri, task = str(act.get("dri", "")), str(act.get("task", ""))
                            if (dri and task and c.team.get(dri) and task not in pending_titles
                                    and len(c.backlog) < self.max_dispatch):
                                c.add_task(task, dri, task_class="meeting-action")
                                pending_titles.add(task)
                except Exception:
                    pass
            # 8. individual initiative (BOUNDED): a creative employee proposes one idea
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
