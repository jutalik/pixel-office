"""Budget guard — a fail-closed spend ceiling for agent-incurred cost.

Preflight: an action that would take total spend past the cap is BLOCKED before
it runs (fail-closed), never after. Recording is atomic under a lock. Cost is
whatever the caller measures (tokens→USD, generation credits, external calls);
this guard only enforces the ceiling and keeps a running total.
"""
from __future__ import annotations

import math
import threading
from dataclasses import dataclass, field
from typing import Dict, Optional


def _finite_nonneg(x: float, what: str) -> float:
    x = float(x)
    if not math.isfinite(x) or x < 0:
        raise ValueError(f"{what} must be a finite, non-negative number, got {x!r}")
    return x


@dataclass
class BudgetState:
    cap_usd: float
    spent_usd: float = 0.0
    per_scope: Dict[str, float] = field(default_factory=dict)


class BudgetGuard:
    def __init__(self, cap_usd: float, *, per_scope_cap_usd: Optional[float] = None):
        self.cap_usd = _finite_nonneg(cap_usd, "cap_usd")
        self.per_scope_cap_usd = (_finite_nonneg(per_scope_cap_usd, "per_scope_cap_usd")
                                  if per_scope_cap_usd is not None else None)
        self._spent = 0.0
        self._per_scope: Dict[str, float] = {}
        self._lock = threading.Lock()

    def remaining(self) -> float:
        with self._lock:
            return max(0.0, self.cap_usd - self._spent)

    def would_exceed(self, cost_usd: float, scope: str = "") -> bool:
        if not math.isfinite(cost_usd) or cost_usd < 0:
            return True  # fail-closed on garbage input
        with self._lock:
            if self._spent + cost_usd > self.cap_usd:
                return True
            if self.per_scope_cap_usd is not None and scope:
                if self._per_scope.get(scope, 0.0) + cost_usd > self.per_scope_cap_usd:
                    return True
            return False

    def charge(self, cost_usd: float, scope: str = "") -> bool:
        """Atomically record a charge IF it fits. Returns False (blocked) if it
        would breach the total or per-scope cap — the caller must not proceed."""
        cost_usd = _finite_nonneg(cost_usd, "cost_usd")
        with self._lock:
            if self._spent + cost_usd > self.cap_usd:
                return False
            if self.per_scope_cap_usd is not None and scope:
                if self._per_scope.get(scope, 0.0) + cost_usd > self.per_scope_cap_usd:
                    return False
            self._spent += cost_usd
            if scope:
                self._per_scope[scope] = self._per_scope.get(scope, 0.0) + cost_usd
            return True

    def state(self) -> BudgetState:
        with self._lock:
            return BudgetState(cap_usd=self.cap_usd, spent_usd=self._spent,
                               per_scope=dict(self._per_scope))
