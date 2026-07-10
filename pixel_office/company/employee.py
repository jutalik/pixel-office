"""Employee identity (docs/COMPANY-LAYER.md §2).

A durable identity — NOT an always-on agent. Cheap to store; it only costs tokens
when the runtime activates it for a task. Isolation (a real account/config-dir) is
provisioned only for roles that own irreversible state (Phase 5); most are
role-scoped executions on the shared runtime.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, Optional

TIERS = ("cheap", "standard", "deep")   # model tier: routine → hard/creative


@dataclass(frozen=True)
class Employee:
    id: str
    title: str                      # real IT role, e.g. "backend engineer"
    persona: str = ""               # short role rules / voice (cached preamble)
    tier: str = "cheap"             # default model tier for this role
    isolated: bool = False          # own account/config-dir (only for stateful roles)

    def validate(self) -> "Employee":
        if not self.id or not self.title:
            raise ValueError("employee needs an id and a title")
        if self.tier not in TIERS:
            raise ValueError(f"tier {self.tier!r} not in {TIERS}")
        return self


class Team:
    def __init__(self):
        self._by_id: Dict[str, Employee] = {}

    def hire(self, emp: Employee) -> Employee:
        emp.validate()
        if emp.id in self._by_id:
            raise ValueError(f"employee id {emp.id!r} already exists")
        self._by_id[emp.id] = emp
        return emp

    def get(self, emp_id: str) -> Optional[Employee]:
        return self._by_id.get(emp_id)

    def all(self):
        return tuple(self._by_id.values())

    def __len__(self):
        return len(self._by_id)
