"""HR — staged, reversible, evidence-based hire/fire (docs/COMPANY-LAYER.md §7).

A lean policy engine (not a standing multi-agent team). It only RECOMMENDS from
evidence — competency (Phase 3) + demand. Termination is a one-way door, so it
always reaches the CEO; the reversible steps (dormancy, reassignment) don't.
The elaborate multi-agent HR "team" is parked in docs/IDEAS.md.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List

from .employee import Team
from .learning import EmployeeMemory
from .mode import OperatingMode

FIRE_THRESHOLD = 0.3     # sustained competency below this on a class → fire candidate
HIRE_FAILURE_MIN = 3     # a class with this many failures + no competent owner → hire


@dataclass
class Recommendation:
    kind: str            # "fire" | "hire"
    target: str          # employee id (fire) or role/task_class (hire)
    reason: str
    needs_ceo: bool      # termination is a one-way door → always True


def review(team: Team, memories: Dict[str, EmployeeMemory], *,
           mode: OperatingMode = None) -> List[Recommendation]:
    mode = mode or OperatingMode()
    recs: List[Recommendation] = []
    current = {e.id for e in team.all()}   # ignore former/non-team memories (stale)

    # FIRE: an employee whose evidence-based competency on their work is clearly
    # low (with enough samples) — staged; permanent termination reaches the CEO.
    for emp in team.all():
        mem = memories.get(emp.id)
        if mem is None:
            continue
        for task_class, _stat in list(mem._stats.items()):   # snapshot — dispatch mutates
            score = mem.competency(task_class)     # this concurrently (assign is lock-free)
            if score is not None and score < FIRE_THRESHOLD:
                recs.append(Recommendation(
                    kind="fire", target=emp.id,
                    reason=f"competency {score} on {task_class} over {mem.samples(task_class)} tasks",
                    needs_ceo=mode.reaches_ceo(one_way_door=True)))   # termination = one-way door
                break

    # HIRE: a task-class the team keeps failing at, with no competent owner —
    # first try tooling/training (not modeled here); this only flags the gap.
    class_fail: Dict[str, int] = {}
    class_has_competent: Dict[str, bool] = {}
    for emp_id, mem in memories.items():
        if emp_id not in current:
            continue   # a former employee's record must not sway current hiring
        for task_class, st in list(mem._stats.items()):   # snapshot (see above)
            class_fail[task_class] = class_fail.get(task_class, 0) + (st.n - st.ok)
            score = mem.competency(task_class)
            if score is not None and score >= FIRE_THRESHOLD:
                class_has_competent[task_class] = True
    for task_class, fails in class_fail.items():
        if fails >= HIRE_FAILURE_MIN and not class_has_competent.get(task_class):
            recs.append(Recommendation(
                kind="hire", target=task_class,
                reason=f"{fails} failures on {task_class} and no competent owner",
                needs_ceo=False))   # a probationary hire is reversible; scale-up gates elsewhere
    return recs


def terminate(team: Team, emp_id: str, *, ceo_approved: bool) -> str:
    """Permanent termination is a one-way door — refuse without CEO approval.
    (Reversible steps like dormancy/reassignment are the caller's default first.)"""
    if not ceo_approved:
        raise PermissionError("termination is irreversible — needs CEO approval")
    if team.get(emp_id) is None:
        raise KeyError(emp_id)
    del team._by_id[emp_id]
    return f"terminated {emp_id}"
