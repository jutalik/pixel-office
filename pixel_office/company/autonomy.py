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

from . import creativity, ideas as _ideas, metrics, roles as _roles, skills, workflows
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
                 meeting_every_s: float = 4 * 3600, idea_gen_fn=None):
        self.company = company
        self.planner_fn = planner_fn or default_planner
        # idea_gen_fn(objective, family, lens, target_kr_text) -> str : OPTIONAL live
        # creativity engine (a real CLI in --live). Called OUTSIDE the company lock;
        # None → deterministic skeletons (0-token demo/tests).
        self.idea_gen_fn = idea_gen_fn
        self.max_dispatch = max_dispatch
        self.review_every_s = review_every_s
        self.radar_every_s = radar_every_s
        # the loop is the SINGLE cadence gate for the radar now (it drives scans off-lock
        # in phase B); align the radar's own interval so it doesn't double-gate and block.
        try:
            company.radar.min_interval_s = radar_every_s
        except Exception:
            pass
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
        self._celebrated: set = set()   # KR ids already celebrated at 100% (fire once)
        self._ticks: int = 0            # monotonic tick counter (idea validation windows)
        self._kr_hist: list = []        # bounded (tick, {kr_id: value}) — for baseline trend

    def _baseline_rate(self, kr_id: str, at_tick: int):
        """The target KR's own per-tick trend BEFORE delivery, from recent history — so
        an idea is credited only for the EXCESS above what the KR was already doing.
        Returns (rate, established): established is False when there isn't enough history
        to establish a trend, in which case the idea is NOT creditable (0 is not
        conservative for a growing KR — it would credit secular growth)."""
        pts = [(t, d[kr_id]) for (t, d) in self._kr_hist if kr_id in d and t <= at_tick]
        if len(pts) < 2:
            return 0.0, False
        (t0, v0) = pts[-min(len(pts), _ideas.BASELINE_WINDOW + 1)]
        (t1, v1) = pts[-1]
        rate = (v1 - v0) / (t1 - t0) if t1 != t0 else 0.0
        return rate, True

    def tick(self, now: float) -> TickReport:
        c = self.company
        r = TickReport()
        self._ticks += 1
        tick_no = self._ticks
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
            do_radar = _due(self._last_radar, now, self.radar_every_s)
            if do_radar:
                self._last_radar = now      # the radar SEARCH (HTTP) runs in phase B, off-lock
            # 2b. initiative DECISION (who/what/lens) — the creative content itself is
            #     generated in phase B (may hit a live CLI), never under the lock.
            initiative_plan = None
            if _due(self._last_initiative, now, self.initiative_every_s):
                self._last_initiative = now
                try:
                    creatives = [e for e in c.team.all() if _roles.is_creative(e)]
                    active = _active_stalled(c, 0.05)
                    if creatives and active:
                        emp = creatives[int(now) % len(creatives)]     # rotate proposers deterministically
                        kr = active[int(now) % len(active)]            # a KR the team is really pushing
                        fam = _roles.family_of(emp.role)
                        lenses = list(creativity.lenses_for(fam)) or ["smallest-reversible"]
                        # steer AWAY from a lens already falsified on this KR (diversify),
                        # falling back to the rotation if every lens has been tried.
                        tried = c.falsified_lenses()
                        fresh = [l for l in lenses if (str(kr.id), l) not in tried]
                        pool = fresh or lenses
                        initiative_plan = {"emp": emp.id, "kr_id": str(kr.id), "kr_text": kr.text,
                                           "kr_target": float(getattr(kr, "target", 0) or 0),
                                           "family": fam, "objective": c.okrs.objective,
                                           "lens": pool[int(now) % len(pool)],
                                           # REAL current trends (from the radar's configured sources)
                                           # seed the idea — empty when no source is set (no fabrication).
                                           "trends": list(getattr(c, "_trends", []))[:5]}
                except Exception:
                    initiative_plan = None
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
        # radar SEARCH (SearXNG/Reddit HTTP) runs OFF-lock too — sequential per-source
        # requests must never freeze /api/company reads.
        radar_rep = None
        if do_radar:
            try:
                radar_rep = c.radar.scan(now)
            except Exception:
                radar_rep = None
        # idea CONTENT generation (D2): a live CLI writes the actual idea in --live;
        # deterministic skeleton otherwise. Done here so the CLI can't freeze the lock.
        idea_content, idea_assumptions, idea_grounding, idea_gen_failed = "", (), "", False
        if initiative_plan and self.idea_gen_fn is not None:
            try:
                raw = str(self.idea_gen_fn(
                    initiative_plan["objective"], initiative_plan["family"],
                    initiative_plan["lens"], initiative_plan["kr_text"],
                    initiative_plan.get("trends", [])) or "")
            except Exception:
                raw = ""
            if raw.strip():
                idea_content, idea_assumptions, idea_grounding = creativity.parse_live_idea(raw)
            else:
                idea_gen_failed = True   # live CLI produced nothing → do NOT fabricate a proposal
        # ---- phase C: record results + cadence work (under lock — pure state) --------
        with c._lock:
            # KR baseline BEFORE this tick's metrics land — the snapshot an idea's
            # delivery is measured against (a later rise must beat this baseline).
            kr_pre = {str(k.id): float(k.current) for k in c.okrs.key_results}
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
                # idea task → delivered (with its target KR's pre-delivery trend) / dropped
                _rec = next((i for i in c.ideas if i.task_id == getattr(task, "id", None)
                             and i.status == _ideas.PURSUED), None)
                _brate, _bok = self._baseline_rate(_rec.target_kr_id, tick_no) if _rec else (0.0, True)
                c.settle_idea_task(task, result, kr_pre, tick_no, baseline_rate=_brate, baseline_ok=_bok)
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
            # 3b. settle delivered ideas against the NOW-current KRs (post-metrics). A
            #     delivered idea whose targeted KR rose strictly after delivery becomes
            #     outcome-ASSOCIATED (correlational, not causal); ambiguous overlaps earn
            #     no individual points; the window elapses to INCONCLUSIVE. Honest.
            kr_now = {str(k.id): float(k.current) for k in c.okrs.key_results}
            try:
                if c.ideas:
                    before = {i.id: i.status for i in c.ideas}
                    c.settle_ideas(kr_now, tick_no)
                    for i in c.ideas:
                        if before.get(i.id) == i.status:
                            continue
                        if i.status == _ideas.ASSOCIATED:
                            c.record_activity("outcome",
                                              f"💡 {i.proposer_id}'s {i.lens} idea — {i.target_kr_id} beat baseline by +{round(i.associated_delta,3)} (assoc., not causal)")
                        elif i.status == _ideas.FAILED_HYPOTHESIS:
                            # a falsified hypothesis is preserved as reusable LEARNING —
                            # no points, no progress, just context for the next attempt.
                            c.record_learning(creativity.learning_from(i, tick_no))
                            c.record_activity("learning", f"↩ {i.lens} on {i.target_kr_id} didn't beat baseline — logged")
            except Exception:
                pass
            # record the post-metrics KR levels so future deliveries can estimate each
            # KR's own trend (bounded history — the baseline for honest attribution).
            self._kr_hist.append((tick_no, kr_now))
            if len(self._kr_hist) > _ideas.BASELINE_WINDOW + 3:
                del self._kr_hist[:-(_ideas.BASELINE_WINDOW + 3)]
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
            if do_radar and radar_rep is not None and getattr(radar_rep, "ran", False):
                try:
                    c._trends = list(radar_rep.trends)   # store the off-lock scan (under lock now)
                    r.scanned = True
                    if radar_rep.trends:
                        c.record_activity("trend", f"scanned trends — {len(radar_rep.trends)} on the radar")
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
            # 8. individual initiative (BOUNDED): the creative employee chosen in phase A
            #    RECORDS an idea (content written by a live CLI in --live, else a
            #    deterministic skeleton) against a specific target KR, and — if reversible
            #    — pursues it as ONE bounded task. The idea earns nothing here; it only
            #    becomes outcome-associated later if that KR actually rises after it ships.
            # skip entirely if a LIVE idea generation failed — never attribute a
            # deterministic skeleton to the employee as if their CLI authored it.
            if initiative_plan is not None and not idea_gen_failed:
                try:
                    # preregister the experiment contract: beat baseline by ≥3% of the
                    # KR target (min 1.0) within the window — fixed BEFORE pursuit so
                    # success can't be redefined after the fact.
                    _thr = max(1.0, 0.03 * initiative_plan.get("kr_target", 0.0))
                    rec = creativity.new_idea_record(
                        initiative_plan["emp"], initiative_plan["lens"], initiative_plan["kr_id"],
                        objective=initiative_plan["objective"], content=idea_content,
                        grounded_in=idea_grounding, proposer_assumptions=idea_assumptions,
                        success_threshold=_thr, evaluation_window=_ideas.VALIDATION_WINDOW_TICKS,
                        created_tick=tick_no)
                    if c.propose_idea(rec) is not None:   # None → ledger full of active ideas, skip
                        c.record_activity("idea", f"{rec.proposer_id} proposed [{rec.lens}] → {initiative_plan['kr_text']}")
                        if rec.reversible and len(c.backlog) < self.max_dispatch:
                            t = Task(title=f"explore [{rec.lens}]: {rec.content}"[:200],
                                     dri=rec.proposer_id, task_class="initiative")
                            c.pursue_idea(rec, t)
                        r.initiatives = 1
                except Exception:
                    pass
            # 9. milestone celebration (HONEST): a Key Result that has actually reached
            #    100% is a real win worth surfacing — recorded ONCE, only on genuine
            #    completion (real metrics in --live, simulated progress in --demo). It
            #    fabricates nothing: no KR is marked done that the numbers didn't finish.
            try:
                for kr in c.okrs.key_results:
                    if kr.progress >= 1.0 and kr.id not in self._celebrated:
                        self._celebrated.add(kr.id)
                        c.record_activity("milestone", f"🎉 goal reached: {kr.text}")
            except Exception:
                pass
            r.ceo_pending = len(c.memos.ceo_queue())
        return r
