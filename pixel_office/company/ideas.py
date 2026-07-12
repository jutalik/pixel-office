"""Idea ledger — an evidence-based 'idea → outcome → reputation' loop (docs/COMPANY-LAYER.md).

The honest core of a creative, productive AI team: an employee proposes an idea
(divergent lens + a target Key Result it aims to move), it gets pursued as one
bounded task, and it earns recognition ONLY from a real outcome — the task
succeeded AND the *specific* KR it targeted actually rose afterward.

Honesty is the whole point, so the wording is deliberately conservative:

- The signal is CORRELATION, not causation: a KR rising after an idea ships is an
  *outcome-associated* observation, never proof the idea caused it. Fields and UI
  say "associated", never "impact"/"drove"/"caused".
- Individual reputation is credited ONLY when attribution is EXCLUSIVE — exactly
  one delivered idea targeted the KR that moved, in the window. If several ideas
  targeted the same moved KR, none gets individual credit (splitting a delta is an
  invented rule); it's team-level recognition only.
- A rise must be observed STRICTLY AFTER delivery (a stored delivered-at tick),
  so delayed polling can't credit pre-delivery progress.
- No outcome within the window → terminal `INCONCLUSIVE` with zero points. Nothing
  stays "pending" forever, and expiry never awards points.

This module is a pure, deterministic settlement engine over IdeaRecords; the
Company owns the ledger and the autonomy loop drives the lifecycle.
"""
from __future__ import annotations

from typing import Dict, List

MAX_IDEAS = 200                 # bounded ledger (oldest terminal records evicted first)
VALIDATION_WINDOW_TICKS = 6     # ticks after delivery to observe an associated rise
BASELINE_WINDOW = 4             # ticks of pre-delivery history used to estimate the KR's own trend

# lifecycle statuses (terminal: ASSOCIATED / AMBIGUOUS / INCONCLUSIVE / DROPPED)
PROPOSED = "proposed"
PURSUED = "pursued"
DELIVERED = "delivered"         # task succeeded; watching the target KR vs its baseline
ASSOCIATED = "associated"       # KR beat baseline by ≥ threshold, EXCLUSIVE attribution → points
AMBIGUOUS = "ambiguous"         # threshold beaten but ≥2 ideas targeted it → team recognition, no points
FAILED_HYPOTHESIS = "failed"    # preregistered threshold NOT met in the window → zero points
INCONCLUSIVE = "inconclusive"   # window expired, no threshold set → zero points
DROPPED = "dropped"             # the pursued task failed → zero points

_TERMINAL = (ASSOCIATED, AMBIGUOUS, FAILED_HYPOTHESIS, INCONCLUSIVE, DROPPED)


def is_terminal(status: str) -> bool:
    return status in _TERMINAL


def settle(ideas: List, kr_current: Dict[str, float], now_tick: int,
           *, window: int = VALIDATION_WINDOW_TICKS) -> int:
    """Move DELIVERED ideas to a terminal state from REAL evidence. `kr_current` is
    the CURRENT value per KR id (observed at now_tick, i.e. strictly after any prior
    delivery). Returns how many ideas were settled this call. Mutates ideas in place.

    Exclusive attribution: among ideas still DELIVERED and targeting a KR that rose
    above its delivery snapshot, credit the single one if it's alone; else mark all
    AMBIGUOUS (no individual points). Delivered ideas past the window with no rise →
    INCONCLUSIVE. Never fabricates a rise; a missing/unknown KR simply can't settle."""
    # Re-baseline ideas delivered THIS tick to the CURRENT (post-metrics) KR level, so
    # a rise that happened *during* the delivery tick is never later mistaken for one
    # that came after it — association credits only strictly-later movement.
    for i in ideas:
        if i.status == DELIVERED and i.delivered_at == now_tick:
            cur = kr_current.get(i.target_kr_id)
            if cur is not None:
                i.kr_snapshot = cur
    delivered = [i for i in ideas if i.status == DELIVERED]
    # group the still-open delivered ideas by the KR they targeted
    by_kr: Dict[str, list] = {}
    for i in delivered:
        by_kr.setdefault(i.target_kr_id, []).append(i)
    settled = 0
    for kr_id, group in by_kr.items():
        cur = kr_current.get(kr_id)
        if cur is None:
            continue
        # DURABLE contention: the moment ≥2 ideas are in flight against one KR, mark ALL
        # of them permanently non-exclusive — so a later, now-alone survivor can't claim
        # exclusive credit for a KR that was confounded while it was running.
        if len(group) >= 2:
            for i in group:
                i.contended = True
        # BASELINE-ADJUSTED: the KR would have drifted `baseline_rate` per tick anyway,
        # so credit only the EXCESS above that expected drift — not secular growth. And
        # never on a KR that actually FELL, or one with no established baseline.
        beat = []
        for i in group:
            if now_tick <= i.delivered_at or not i.baseline_ok:
                continue
            elapsed = now_tick - i.delivered_at
            expected = i.kr_snapshot + i.baseline_rate * elapsed
            i.raw_delta = round(cur - i.kr_snapshot, 4)
            adjusted = cur - expected
            if adjusted >= i.success_threshold and adjusted > 0 and cur > i.kr_snapshot:
                i.associated_delta = round(adjusted, 4)   # provisional; finalized below
                beat.append(i)
        if not beat:
            continue
        # EXCLUSIVE only when this is the SOLE delivered idea for the KR AND it was never
        # contended over its lifetime — otherwise the excess can't be attributed to one
        # idea, so it's team recognition (AMBIGUOUS), no individual points.
        exclusive = len(group) == 1 and not beat[0].contended
        if exclusive:
            i = beat[0]
            i.status = ASSOCIATED
            i.outcome_points = i.associated_delta       # earned ONLY here (exclusive attribution)
            i.settled_at = now_tick
            settled += 1
        else:
            for i in beat:
                i.status = AMBIGUOUS
                i.outcome_points = 0.0
                i.settled_at = now_tick
                settled += 1
    for i in delivered:
        if i.status == DELIVERED and (now_tick - i.delivered_at) >= i.evaluation_window:
            # window elapsed without beating baseline+threshold. A PREREGISTERED
            # threshold makes this a clear falsification; otherwise just inconclusive.
            i.status = FAILED_HYPOTHESIS if i.success_threshold > 0 else INCONCLUSIVE
            i.outcome_points = 0.0
            i.settled_at = now_tick
            settled += 1
    return settled


def evict(ideas: List, *, cap: int = MAX_IDEAS) -> None:
    """Keep the ledger bounded WITHOUT dropping active records or breaking task links:
    only terminal ideas are eligible for eviction, oldest first."""
    if len(ideas) <= cap:
        return
    over = len(ideas) - cap
    # collect indices of terminal records in insertion order; evict the oldest of them
    victims = [idx for idx, i in enumerate(ideas) if is_terminal(i.status)][:over]
    vset = set(victims)
    ideas[:] = [i for idx, i in enumerate(ideas) if idx not in vset]


def proposer_reputation(ideas: List) -> Dict[str, float]:
    """Per-proposer outcome-associated points = sum of EXCLUSIVELY-associated ideas
    (evidence-based; a proposer with no validated outcome simply isn't listed)."""
    rep: Dict[str, float] = {}
    for i in ideas:
        if i.status == ASSOCIATED and i.outcome_points:
            rep[i.proposer_id] = round(rep.get(i.proposer_id, 0.0) + i.outcome_points, 4)
    return rep
