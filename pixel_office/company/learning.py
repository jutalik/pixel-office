"""Self-learning — evidence-first, mostly deterministic (docs/COMPANY-LAYER.md §5).

Per-employee, isolated. Lessons are derived from EVIDENCE (task outcomes,
rollbacks, reviewer verdicts), never self-rated. Competency is scored per
task-class from outcomes and reports "insufficient evidence" below a sample
floor rather than inventing a number. Deterministic and zero-token; an optional
LLM reflection can enrich a lesson, but the core runs on rules.

(The elaborate 4-tier memory / recursive distillation is parked in docs/IDEAS.md;
this is the lean version that actually drives HR + routing.)
"""
from __future__ import annotations

import itertools
from dataclasses import dataclass, field
from typing import Dict, List, Optional

_ev_ids = itertools.count(1)
MIN_SAMPLES = 3   # below this, competency is "insufficient evidence"


@dataclass(frozen=True)
class Evidence:
    kind: str            # e.g. "task_done" | "task_blocked" | "rolled_back" | "reviewed"
    task_class: str      # the kind of work (e.g. "backend", "writing")
    ok: bool
    ref: str = ""        # a task id / commit / verdict pointer (no content)
    id: int = field(default_factory=lambda: next(_ev_ids))


@dataclass(frozen=True)
class Lesson:
    text: str
    evidence_id: int
    task_class: str
    confidence: float = 0.5


@dataclass
class _ClassStat:
    n: int = 0
    ok: int = 0
    rolled_back: int = 0

    @property
    def score(self) -> float:
        if self.n == 0:
            return 0.0
        # simple evidence-based score: success rate, penalized by rollbacks
        return max(0.0, (self.ok - self.rolled_back) / self.n)


class EmployeeMemory:
    """One employee's private, evidence-first memory + competency."""

    def __init__(self, employee_id: str):
        self.employee_id = employee_id
        self.evidence: List[Evidence] = []
        self.lessons: List[Lesson] = []
        self._stats: Dict[str, _ClassStat] = {}

    # ---- record outcomes (deterministic) ------------------------------------

    def record(self, kind: str, task_class: str, ok: bool, *, ref: str = "",
               rolled_back: bool = False) -> Evidence:
        ev = Evidence(kind=kind, task_class=task_class, ok=ok, ref=ref)
        self.evidence.append(ev)
        st = self._stats.setdefault(task_class, _ClassStat())
        st.n += 1
        st.ok += 1 if ok else 0
        st.rolled_back += 1 if rolled_back else 0
        # derive a rule-based lesson only on signal (failure / rollback), not routine
        if not ok or rolled_back:
            self.lessons.append(Lesson(
                text=f"{'rollback' if rolled_back else 'failure'} on {task_class} ({ref or ev.id})",
                evidence_id=ev.id, task_class=task_class, confidence=0.6))
        return ev

    def add_lesson(self, lesson: Lesson) -> Lesson:
        self.lessons.append(lesson)
        return lesson

    # ---- retrieval + competency ---------------------------------------------

    def recall(self, task_class: str = None, k: int = 5) -> List[Lesson]:
        pool = [ls for ls in self.lessons if task_class is None or ls.task_class == task_class]
        return sorted(pool, key=lambda ls: ls.confidence, reverse=True)[:k]

    def competency(self, task_class: str) -> Optional[float]:
        """Evidence-based score in [0,1], or None if below the sample floor."""
        st = self._stats.get(task_class)
        if st is None or st.n < MIN_SAMPLES:
            return None   # "insufficient evidence" — never invent a score
        return round(st.score, 3)

    def samples(self, task_class: str) -> int:
        st = self._stats.get(task_class)
        return st.n if st else 0
