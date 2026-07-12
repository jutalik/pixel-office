"""Company — the facade that bundles the layer for one project.

Ties together the operating mode, the team, the OKR tree, the decision memos, and
the org runtime. Exposes a small summary + the CEO's card queue for the dashboard.
"""
from __future__ import annotations

import threading
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

MAX_ACTIVITY = 50   # the CEO's "what did my company do" feed is bounded (memory-safe)


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
        self.product_url: str = ""       # the live product's base URL (growth-loop KPI polling)
        self.simulated: bool = False     # True in `--demo`: progress is simulated, labelled as such
        self.backlog: list = []          # pending Tasks (autonomy loop drains this)
        self.workflows: dict = {}        # kr_id -> WorkflowRun (opt-in workflow dispatch)
        self._wf_task_kr: dict = {}      # task.id -> kr_id (attribution for advance_workflow)
        self.ideas: list = []            # IdeaRecord ledger (propose→outcome-associated; ideas.py)
        self.learnings: list = []        # LearningRecord ledger — what FAILED ideas taught (no points)
        self.activity: list = []         # bounded feed of what the company did (CEO watch)
        # guards company state (memos/backlog/trends/okrs/activity) when the
        # autonomy thread mutates it while the API reads it. RLock: summary() ->
        # hr_review() etc. re-enter safely (and record_activity re-enters tick).
        self._lock = threading.RLock()

    def add_task(self, title: str, dri: str, task_class: str = "general"):
        from .runtime import Task
        t = Task(title=title, dri=dri, task_class=task_class)
        self.backlog.append(t)
        return t

    # ---- workflows: ordered playbooks dispatched one honest step at a time -------
    def start_workflow(self, kr_id, workflow_id):
        from .workflows import WorkflowRun
        run = WorkflowRun(kr_id=str(kr_id), workflow_id=str(workflow_id))
        self.workflows[str(kr_id)] = run
        return run

    def mark_workflow_task(self, task_id, kr_id) -> None:
        """Remember which KR/workflow a dispatched task belongs to, so its result
        can advance the right run (task ids are unique per process)."""
        try:
            self._wf_task_kr[int(task_id)] = str(kr_id)
        except (TypeError, ValueError):
            pass

    def advance_workflow(self, task, result) -> None:
        """Advance a workflow one step on a REAL result: success → next step (complete
        past the last), failure → halt (blocked). Never fabricates progress. Fail-open
        so a bug here can't wedge the dispatch loop."""
        try:
            kr_id = self._wf_task_kr.pop(int(getattr(task, "id", -1)), None)
            if kr_id is None:
                return   # not a workflow task (e.g. the default planner) → no-op
            run = self.workflows.get(kr_id)
            if run is None or run.done:
                return
            from .workflows import get as _wf_get
            wf = _wf_get(run.workflow_id)
            if getattr(result, "ok", False):
                run.blocked = False
                run.retries = 0            # real progress → fresh retry budget for the next step
                run.step_index += 1
                if wf is None or run.step_index >= len(wf.steps):
                    run.done = True
                    self.record_activity("workflow", f"{run.workflow_id} complete ({kr_id})")
                else:
                    self.record_activity("workflow", f"{run.workflow_id}: {wf.steps[run.step_index].name} next")
            else:
                run.blocked = True   # halt — a failed step needs attention (clear_workflow to retry)
        except Exception:
            pass

    def clear_workflow(self, kr_id) -> bool:
        """Recovery: un-block a halted workflow so its failed step retries next tick.
        BOUNDED — after MAX_RETRIES failures on the same step the run is abandoned
        instead of retried forever (no infinite token burn on a step that keeps
        failing). Steps still only advance on real success; retries reset on progress."""
        from .workflows import MAX_RETRIES
        run = self.workflows.get(str(kr_id))
        if not (run and run.blocked and not run.abandoned):
            return False
        if run.retries >= MAX_RETRIES:
            run.abandoned = True   # give up retrying — needs a human, not another auto-retry
            self.record_activity("workflow", f"{run.workflow_id} abandoned after {run.retries} retries ({kr_id})")
            return False
        run.retries += 1
        run.blocked = False
        return True

    def workflows_view(self) -> list:
        from .workflows import get as _wf_get
        with self._lock:
            out = []
            for run in self.workflows.values():
                wf = _wf_get(run.workflow_id)
                nsteps = len(wf.steps) if wf else 0
                step_name = wf.steps[run.step_index].name if (wf and 0 <= run.step_index < nsteps) else ""
                out.append({"kr_id": run.kr_id, "workflow_id": run.workflow_id,
                            "step": run.step_index, "steps": nsteps, "step_name": step_name,
                            "done": run.done, "blocked": run.blocked,
                            "retries": run.retries, "abandoned": run.abandoned})
            return out

    # ---- idea ledger: propose → pursue → deliver → outcome-associated (ideas.py) ----
    def propose_idea(self, record):
        """Add a proposed idea to the ledger (HARD bounded). Reclaims terminal slots
        first; if the ledger is still full of ACTIVE records, the proposal is skipped
        (returns None) rather than dropping an in-flight idea/task link. Called under
        the tick lock."""
        from . import ideas as _ideas
        _ideas.evict(self.ideas)
        if len(self.ideas) >= _ideas.MAX_IDEAS:
            return None
        self.ideas.append(record)
        return record

    def pursue_idea(self, record, task) -> None:
        """Link a bounded exploration task to an idea and enqueue it (no fabricated
        progress — the idea only earns anything if this task really succeeds)."""
        from . import ideas as _ideas
        record.task_id = getattr(task, "id", None)
        record.status = _ideas.PURSUED
        self.backlog.append(task)

    def settle_idea_task(self, task, result, kr_current: dict, now_tick: int,
                         baseline_rate: float = 0.0, baseline_ok: bool = True) -> None:
        """On a pursued idea's task result: success → DELIVERED + snapshot the target KR
        AND its pre-delivery trend (baseline_rate — what the KR would do on its own);
        failure → DROPPED (zero points, honest)."""
        from . import ideas as _ideas
        tid = getattr(task, "id", None)
        if tid is None:
            return
        rec = next((i for i in self.ideas if i.task_id == tid and i.status == _ideas.PURSUED), None)
        if rec is None:
            return
        if getattr(result, "ok", False):
            rec.status = _ideas.DELIVERED
            rec.delivered_at = int(now_tick)
            rec.kr_snapshot = float(kr_current.get(rec.target_kr_id, 0.0))
            rec.baseline_rate = float(baseline_rate)
            rec.baseline_ok = bool(baseline_ok)
        else:
            rec.status = _ideas.DROPPED
            rec.settled_at = int(now_tick)

    def settle_ideas(self, kr_current: dict, now_tick: int) -> int:
        from . import ideas as _ideas
        n = _ideas.settle(self.ideas, kr_current, int(now_tick))
        _ideas.evict(self.ideas)
        return n

    MAX_LEARNINGS = 60
    def record_learning(self, learning) -> None:
        """Preserve what a failed experiment taught (bounded). Never affects points."""
        self.learnings.append(learning)
        if len(self.learnings) > self.MAX_LEARNINGS:
            del self.learnings[:-self.MAX_LEARNINGS]

    def falsified_lenses(self, recent: int = 20) -> set:
        """Recently-falsified (kr_id, lens) pairs — future proposals steer AWAY from
        an approach already shown not to beat baseline on that KR (portfolio diversity)."""
        return {(l.target_kr_id, l.lens) for l in self.learnings[-recent:]}

    def learnings_view(self, limit: int = 6) -> list:
        with self._lock:
            return [{"proposer": l.proposer_id, "lens": l.lens, "target": l.target_kr_id,
                     "falsified": l.falsified} for l in self.learnings[-limit:]]

    def ideas_view(self, limit: int = 6) -> dict:
        """Honest idea board for the CEO panel: associated outcomes (correlational,
        never causal), plus what's still in flight and per-proposer standing."""
        from . import ideas as _ideas
        with self._lock:
            assoc = [i for i in self.ideas if i.status == _ideas.ASSOCIATED]
            assoc.sort(key=lambda i: i.outcome_points, reverse=True)
            pending = [i for i in self.ideas if i.status in (_ideas.PROPOSED, _ideas.PURSUED, _ideas.DELIVERED)]
            def row(i):
                return {"proposer": i.proposer_id, "lens": i.lens, "content": i.content,
                        "target": i.target_kr_id, "status": i.status, "grounded_in": i.grounded_in,
                        "delta": round(i.associated_delta, 3), "points": round(i.outcome_points, 3)}
            rep = _ideas.proposer_reputation(self.ideas)
            top = sorted(rep.items(), key=lambda kv: kv[1], reverse=True)[:limit]
            # neutral outcome tally — failures/inconclusive are shown as counts, never
            # as a failure score or hidden negative reputation (honest transparency).
            counts: dict = {}
            for i in self.ideas:
                counts[i.status] = counts.get(i.status, 0) + 1
            return {"associated": [row(i) for i in assoc[:limit]],
                    "pending": [row(i) for i in pending[-limit:]],
                    "reputation": [{"proposer": p, "points": round(v, 3)} for p, v in top],
                    "outcomes": counts}

    def record_activity(self, kind: str, text: str) -> None:
        """Append one real thing the company did (plan/work/decision/trend/hr).
        Bounded — the oldest entries fall off so the feed can't grow without limit."""
        with self._lock:
            self.activity.append({"kind": str(kind)[:16], "text": str(text)[:160]})
            if len(self.activity) > MAX_ACTIVITY:
                del self.activity[:-MAX_ACTIVITY]

    def activity_view(self, limit: int = 12) -> list:
        with self._lock:
            n = max(1, min(int(limit) if isinstance(limit, int) else 12, MAX_ACTIVITY))
            return list(self.activity[-n:])

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

    def roster(self) -> list:
        """Org structure for the office floor: each employee + their department.
        Real org data (from roles), so avatars can group into department rooms."""
        from . import skills as _skills
        from .routing import department_of
        with self._lock:
            out = []
            for e in self.team.all():
                mem = self.runtime.memory_of(e.id)
                # evidence-based proficiency per skill: a real [0,1] once proven, or
                # None ("learning") below the sample floor — never an invented score.
                prof = {s: _skills.aggregate_proficiency(mem, s) for s in e.skills}
                from . import roles as _roles
                out.append({"id": e.id, "title": e.title, "dept": department_of(e),
                            "role": e.role, "skills": list(e.skills),
                            "workflows": list(e.workflows), "tier": e.tier,
                            "proficiency": prof,
                            "creative": _roles.is_creative(e),      # role-derived, single source
                            "style": mem.top_trait("focus")})       # evidence-based focus, or None
            return out

    def hr_review(self) -> list:
        return hr_mod.review(self.team, self.runtime.memories, mode=self.mode)

    def scan_trends(self, now: float) -> list:
        rep = self.radar.scan(now)
        if rep.ran:                        # a scan that ran REPLACES the set — even with fewer
            self._trends = rep.trends      # (or zero) trends, so expired ones don't linger
        return self._trends

    def set_trends(self, trends) -> None:
        """Store trends scanned OUTSIDE the lock (autonomy phase B) — see scan_trends."""
        with self._lock:
            self._trends = list(trends or [])

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
            "simulated": self.simulated,
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
