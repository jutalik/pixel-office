"""Trend radar — budgeted, recurring research (docs/COMPANY-LAYER.md §8).

Scans the latest trends for the company's domain on a cadence, dedupes
deterministically, and distills a short report that feeds the weekly review /
backlog. The web search itself is a pluggable `search_fn` (a real search in
prod, a stub in tests → zero tokens). A cadence gate is the budget: it never
runs unbounded.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable, List, Optional

# search_fn(query) -> list of short trend strings (headlines/topics, no bodies)
SearchFn = Callable[[str], List[str]]


@dataclass
class TrendReport:
    query: str
    trends: List[str] = field(default_factory=list)   # deduped, capped
    ran: bool = True                                   # False when the cadence gate skipped


@dataclass
class TrendRadar:
    objective: str
    niche: str = ""
    search_fn: Optional[SearchFn] = None
    min_interval_s: float = 6 * 3600.0      # budget: at most every 6h by default
    max_trends: int = 8
    trend_ttl_s: float = 24 * 3600.0        # RECENCY: a trend may resurface after this and
    #                                         stale ones expire — "current" means recent, not ever
    _last_run: float = field(default=None, repr=False)
    _seen: dict = field(default_factory=dict, repr=False)   # key -> (display, last-seen time)

    def query(self) -> str:
        bits = [b for b in (self.niche, self.objective, "latest trends 2026") if b]
        return " · ".join(bits)

    def scan(self, now: float) -> TrendReport:
        q = self.query()
        # cadence gate = the token/cost budget
        if self._last_run is not None and (now - self._last_run) < self.min_interval_s:
            return TrendReport(query=q, trends=[], ran=False)
        self._last_run = now
        if self.search_fn is None:
            return TrendReport(query=q, trends=[], ran=True)
        try:
            raw = self.search_fn(q) or []
        except Exception:
            raw = []                         # fail-open: a search error is not fatal
        for item in raw:
            key = str(item).strip().lower()
            if key:
                prev = self._seen.get(key)
                display = prev[0] if prev else str(item).strip()   # keep first-seen text
                self._seen[key] = (display, now)                   # refresh its recency stamp
        # prune expired entries → the set reflects only what is still RECENT (bounded)
        self._seen = {k: v for k, v in self._seen.items() if (now - v[1]) < self.trend_ttl_s}
        # the CURRENT active set: most-recently-seen first, capped
        active = sorted(self._seen.values(), key=lambda dv: dv[1], reverse=True)
        return TrendReport(query=q, trends=[d for (d, _t) in active][:self.max_trends], ran=True)
