"""Approval envelopes — approve once, operate inside (docs/COMPANY-LAYER.md §4).

The CEO approves a *purpose + action class + environment + max cost + expiry*
ONE time; matching reversible actions then just happen without re-asking. This
is what keeps autonomy high while the CEO stays hands-off. Irreversible one-way
doors are never covered by an envelope — they always need a fresh sign-off.
"""
from __future__ import annotations

import itertools
import math
import threading
from dataclasses import dataclass, field
from typing import List, Optional

_ids = itertools.count(1)


@dataclass
class Envelope:
    purpose: str
    action_class: str                # e.g. "spend" | "deploy:staging" | "external_send"
    environment: str = "any"         # e.g. "staging" | "prod" | "any"
    max_cost_usd: float = 0.0        # 0 = no spend allowed under this envelope
    expires_at: float = 0.0          # epoch seconds; 0 = never
    spent_usd: float = 0.0
    id: int = field(default_factory=lambda: next(_ids))
    revoked: bool = False

    def active(self, now: float) -> bool:
        return not self.revoked and (self.expires_at == 0.0 or self.expires_at > now)


class EnvelopeStore:
    def __init__(self):
        self._envs: List[Envelope] = []
        self._lock = threading.Lock()

    def approve(self, env: Envelope) -> Envelope:
        with self._lock:
            self._envs.append(env)
        return env

    def revoke(self, env_id: int) -> bool:
        with self._lock:
            for e in self._envs:
                if e.id == env_id:
                    e.revoked = True
                    return True
        return False

    def covers(self, *, purpose: str, action_class: str, environment: str, cost_usd: float,
               one_way_door: bool, now: float) -> Optional[Envelope]:
        """Return an active envelope that authorizes this action, or None. A
        one-way (irreversible) door is NEVER covered — it always needs the CEO.
        The action's `purpose` must match the envelope's approved purpose, so an
        envelope approved for one purpose can't be spent on an unrelated one."""
        if one_way_door or not math.isfinite(cost_usd) or cost_usd < 0:
            return None
        with self._lock:
            for e in self._envs:
                if not e.active(now):
                    continue
                if e.purpose != purpose or e.action_class != action_class:
                    continue
                if e.environment != "any" and e.environment != environment:
                    continue
                if e.spent_usd + cost_usd > e.max_cost_usd:
                    continue
                return e
            return None

    def charge(self, env: Envelope, cost_usd: float, now: float) -> bool:
        """Atomically record spend against an envelope if it still fits."""
        if not math.isfinite(cost_usd) or cost_usd < 0:
            raise ValueError("cost_usd must be a finite, non-negative number")
        with self._lock:
            if not env.active(now) or env.spent_usd + cost_usd > env.max_cost_usd:
                return False
            env.spent_usd += cost_usd
            return True
