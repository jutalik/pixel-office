"""OKRs — the goal tree (docs/COMPANY-LAYER.md §3).

Objective = the CEO's final goal (immutable without the CEO). Key Results are
measurable weekly/monthly targets, updated from real product metrics. Pure and
deterministic — fully e2e-testable, zero tokens.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import List

CADENCES = ("weekly", "monthly")


def _finite(x) -> float:
    x = float(x)
    if not math.isfinite(x):
        raise ValueError(f"expected a finite number, got {x!r}")
    return x


@dataclass
class KeyResult:
    id: str
    text: str
    target: float
    current: float = 0.0
    cadence: str = "weekly"          # weekly | monthly
    metric: str = ""                 # which KPI feeds it (name keyword)

    @property
    def progress(self) -> float:
        if not math.isfinite(self.current) or not math.isfinite(self.target) or self.target <= 0:
            return 0.0
        return max(0.0, min(1.0, self.current / self.target))

    @property
    def done(self) -> bool:
        return self.progress >= 1.0


@dataclass
class OKRTree:
    objective: str                                   # the CEO's final goal
    key_results: List[KeyResult] = field(default_factory=list)

    def add_kr(self, kr: KeyResult) -> KeyResult:
        if kr.cadence not in CADENCES:
            raise ValueError(f"cadence {kr.cadence!r} not in {CADENCES}")
        if any(k.id == kr.id for k in self.key_results):
            raise ValueError(f"duplicate KR id {kr.id!r}")
        self.key_results.append(kr)
        return kr

    def update(self, kr_id: str, current: float) -> KeyResult:
        current = _finite(current)   # reject nan/inf so progress math stays sane
        for k in self.key_results:
            if k.id == kr_id:
                k.current = current
                return k
        raise KeyError(kr_id)

    def apply_metrics(self, metrics: dict) -> int:
        """Update KRs whose `metric` keyword matches a metric name (growth loop)."""
        updated = 0
        for k in self.key_results:
            if not k.metric:
                continue
            for name, value in metrics.items():
                if (k.metric.lower() in str(name).lower()
                        and isinstance(value, (int, float)) and not isinstance(value, bool)
                        and math.isfinite(value)):
                    k.current = float(value)
                    updated += 1
                    break
        return updated

    def progress(self, cadence: str = None) -> float:
        krs = [k for k in self.key_results if cadence is None or k.cadence == cadence]
        return sum(k.progress for k in krs) / len(krs) if krs else 0.0

    def stalled(self, threshold: float = 0.1) -> List[KeyResult]:
        """KRs below `threshold` progress — candidates for a decision memo."""
        return [k for k in self.key_results if k.progress < threshold]
