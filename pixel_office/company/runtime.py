"""Org runtime — the shared, event-driven execution layer (docs/COMPANY-LAYER.md §0).

Employees are dormant identities; the runtime wakes one to do a task. Employee
*reasoning* is a pluggable EXECUTOR: a deterministic stub in tests (zero tokens,
fully e2e-testable), a real CLI-agent activation in production. As an employee
works, the runtime emits RawEvents (cli="company", source="hook") into the SAME
telemetry pipeline, so employees appear as avatars right next to CLI agents.
"""
from __future__ import annotations

import itertools
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Callable, List, Optional

from ..telemetry.contract import RawEvent
from .employee import Employee, Team
from .learning import EmployeeMemory

_task_ids = itertools.count(1)


@dataclass
class Task:
    title: str
    dri: str                         # the accountable employee id
    task_class: str = "general"      # kind of work (drives per-class competency)
    id: int = 0

    def __post_init__(self):
        if not self.id:
            self.id = next(_task_ids)


@dataclass
class TaskResult:
    task_id: int
    employee_id: str
    ok: bool
    summary: str = ""


# executor(employee, task) -> TaskResult. The stub never calls a model.
Executor = Callable[[Employee, Task], TaskResult]
# sink(RawEvent) -> None. Where employee-activity events go (e.g. hub.ingest).
Sink = Callable[[RawEvent], None]


def deterministic_executor(emp: Employee, task: Task) -> TaskResult:
    """Zero-token stub: pretends the employee did the work. For tests + demos."""
    return TaskResult(task_id=task.id, employee_id=emp.id, ok=True,
                      summary=f"{emp.title} handled: {task.title}")


class OrgRuntime:
    def __init__(self, team: Team, *, host_id: str = "local", company_id: str = "company",
                 executor: Executor = deterministic_executor, sink: Optional[Sink] = None):
        self.team = team
        self.host_id = host_id
        self.company_id = company_id
        self.executor = executor
        self.sink = sink
        self._seq = itertools.count(1)
        self.memories: dict = {}     # employee_id -> EmployeeMemory (evidence-first)

    def memory_of(self, emp_id: str) -> EmployeeMemory:
        return self.memories.setdefault(emp_id, EmployeeMemory(emp_id))

    def _emit(self, emp_id: str, kind: str) -> None:
        if self.sink is None:
            return
        ev = RawEvent.from_dict({
            "host_id": self.host_id, "cli": "company", "session_id": self.company_id,
            "agent_id": emp_id, "seq": next(self._seq),
            "ts": datetime.now(timezone.utc).isoformat(), "source": "hook", "kind": kind,
        })
        try:
            self.sink(ev)
        except Exception:
            pass  # telemetry fails open — never breaks the actual work

    def assign(self, task: Task) -> TaskResult:
        """Dispatch a task to its DRI. Emits Working → Done/Blocked as it goes."""
        emp = self.team.get(task.dri)
        if emp is None:
            raise KeyError(f"no employee {task.dri!r} to own {task.title!r}")
        self._emit(emp.id, "Working")
        try:
            result = self.executor(emp, task)
        except Exception as e:
            self._emit(emp.id, "Blocked")
            self.memory_of(emp.id).record("task_blocked", task.task_class, False, ref=str(task.id))
            return TaskResult(task.id, emp.id, ok=False, summary=f"error: {e}")
        if not isinstance(result, TaskResult):   # a broken executor must not crash the runtime
            self._emit(emp.id, "Blocked")
            self.memory_of(emp.id).record("task_blocked", task.task_class, False, ref=str(task.id))
            return TaskResult(task.id, emp.id, ok=False, summary="executor returned no valid result")
        self._emit(emp.id, "Done" if result.ok else "Blocked")
        # learn from the outcome (evidence-first competency; deterministic)
        self.memory_of(emp.id).record("task_done" if result.ok else "task_blocked",
                                      task.task_class, result.ok, ref=str(task.id))
        return result

    def assign_all(self, tasks: List[Task]) -> List[TaskResult]:
        return [self.assign(t) for t in tasks]
