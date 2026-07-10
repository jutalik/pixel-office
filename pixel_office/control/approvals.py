"""Approval gate — privileged actions fail CLOSED.

Mirrors the pixel-office supervisor's field-tested design, minimized for OSS:
- `classify()` is a deterministic, fail-closed server-side risk detector. It is
  a SAFETY BELT for a trusted operator, NOT a security boundary against an
  adversary (obfuscation/base64/multilingual paraphrase can slip past) — the
  real gate is at the point the tool actually runs. Declared action type can
  only ESCALATE, never downgrade, the detected risk.
- Approvals are SINGLE-USE and EXPIRE; claiming one is atomic (no double-spend).
- Every gated action writes an immutable audit record BEFORE it runs; the record
  holds metadata + a salted prompt HASH, never the prompt text or any secret.
"""
from __future__ import annotations

import hashlib
import hmac
import re
import secrets
import threading
from dataclasses import dataclass
from typing import Dict, List, Optional

# risk category -> patterns that force a gate even if the caller declared "task"
RISK_PATTERNS = {
    "deploy": r"\b(deploy|release|ship|publish|rollout|go[\s-]?live)\b",
    "spend": r"\b(purchase|buy|pay|charge|subscribe|checkout|invoice|\$\d)\b",
    "delete": r"\b(delete|drop|rm\s+-rf|truncate|wipe|destroy|purge)\b",
    "external_send": (r"\b(tweet|webhook|notify\s+\w|email\s+\w|post\s+to|publish\s+to|"
                      r"send\s+(a\s+|an\s+|the\s+)?(email|message|dm|text|sms|notification))\b"),
    "prod_change": r"\b(prod|production|migrate|alter\s+table|dns|firewall)\b",
    "grant_access": r"\b(grant|chmod|sudo|add[\s-]?user|api[\s-]?key|token|permission)\b",
}
_COMPILED = {k: re.compile(v, re.IGNORECASE) for k, v in RISK_PATTERNS.items()}

GATED_ACTIONS = frozenset(RISK_PATTERNS)


def classify(text: str) -> List[str]:
    """Return the risk categories detected in `text` (fail-closed, deterministic)."""
    t = str(text or "")
    return sorted(k for k, rx in _COMPILED.items() if rx.search(t))


@dataclass
class Approval:
    token: str
    action_type: str      # "+"-joined sorted risk categories this approval covers
    scope: str
    expires_at: float
    approved: bool = False  # must be explicitly approved before it can be claimed
    used: bool = False


@dataclass
class AuditRecord:
    action_type: str
    scope: str
    decision: str        # requested | approved | consumed | denied | auto-gated
    prompt_hash: str     # salted HMAC — never the text
    at: float


class ApprovalStore:
    """In-memory approvals + audit. A real deployment persists these; the shape
    is what matters for Phase 6 (SQLite persistence is a drop-in later)."""

    def __init__(self, *, ttl_s: float = 900.0, secret: Optional[bytes] = None):
        self.ttl_s = ttl_s
        self._secret = secret or secrets.token_bytes(32)
        self._approvals: Dict[str, Approval] = {}
        self.audit: List[AuditRecord] = []
        self._lock = threading.Lock()  # makes approve/claim atomic in-process

    def _hash(self, text: str) -> str:
        return hmac.new(self._secret, str(text or "").encode(), hashlib.sha256).hexdigest()[:16]

    def _record(self, action_type, scope, decision, prompt, now):
        self.audit.append(AuditRecord(action_type, scope, decision, self._hash(prompt), now))

    def effective_categories(self, declared: str, prompt: str) -> List[str]:
        """Escalate-only UNION: every detected category PLUS a gated declared one.
        A declared type never shrinks the set (declared 'deploy' + detected
        'delete' gates BOTH), so the approval is bound to the full risk surface."""
        cats = set(classify(prompt))
        if declared in GATED_ACTIONS:
            cats.add(declared)
        return sorted(cats)

    def request(self, declared: str, scope: str, prompt: str, now: float) -> Optional[Approval]:
        cats = self.effective_categories(declared, prompt)
        if not cats:
            self._record(declared or "task", scope, "auto-allowed", prompt, now)
            return None  # no gate needed
        action = "+".join(cats)
        token = secrets.token_urlsafe(18)
        appr = Approval(token=token, action_type=action, scope=scope,
                        expires_at=now + self.ttl_s)
        with self._lock:
            self._approvals[token] = appr
        self._record(action, scope, "requested", prompt, now)
        return appr

    def approve(self, token: str, now: float) -> bool:
        with self._lock:
            appr = self._approvals.get(token)
            if not appr or appr.used or appr.expires_at <= now:
                return False
            appr.approved = True
        self._record(appr.action_type, appr.scope, "approved", "", now)
        return True

    def claim(self, token: str, now: float) -> Optional[Approval]:
        """Atomically consume a single-use approval that was explicitly approved
        and is unexpired. Returns it, or None (denied)."""
        with self._lock:
            appr = self._approvals.get(token)
            ok = bool(appr) and appr.approved and not appr.used and appr.expires_at > now
            if ok:
                appr.used = True  # atomic under the lock — no double-spend
        if not ok:
            self._record(appr.action_type if appr else "unknown",
                         appr.scope if appr else "", "denied", "", now)
            return None
        self._record(appr.action_type, appr.scope, "consumed", "", now)
        return appr
