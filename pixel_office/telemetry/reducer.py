"""Deterministic reducer: raw events -> current per-agent state.

Model (revised 2026-07-10 after the Phase-0 review — see docs/DECISIONS.md):
- Hook and tailer are independent observers with independent seq numbering, so
  the reducer keeps ONE FRONTIER PER (agent, source): the latest event applied
  from that source's stream. Within a stream, latest seq wins (order-invariant);
  equal seq resolves by (ts, kind) so replay is deterministic even against a
  buggy adapter that reuses a seq.
- The EFFECTIVE activity for an agent merges its frontiers: among the frontiers
  fresh within GRACE seconds of the freshest one (event timestamps only — no
  wall clock, so replay stays deterministic), the highest-precedence source
  wins (hook > tailer). A dead hook stream ages out of the grace window and the
  tailer takes over automatically.
- State is bounded: O(agents x sources). There is no per-seq history map.
- Unknown kinds are ignored; `done` is only ever produced by a real terminal
  event; nothing here fabricates or regresses state.

Liveness (stale/disconnected) is time-dependent and therefore derived in the
view function, kept out of the reducer so replay stays deterministic.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from types import MappingProxyType
from typing import Iterable, List, Mapping, Optional, Tuple

from .contract import AgentKey, RawEvent, SOURCE_PRECEDENCE, agent_key
from .normalize import normalize

#: Cross-source handover window (seconds, compared between EVENT timestamps).
#: A frontier lagging more than this behind the freshest frontier is ignored
#: when picking the effective state — so a dead hook stream hands over to the
#: tailer, while a merely-slower observer within the window defers to precedence.
DEFAULT_GRACE_S = 10.0

_EPOCH = datetime(1970, 1, 1, tzinfo=timezone.utc)


def _parse_ts(ts: str) -> datetime:
    try:
        dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
    except ValueError:
        return _EPOCH
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


@dataclass(frozen=True)
class Frontier:
    activity: str
    seq: int
    ts: str
    kind: str


@dataclass(frozen=True)
class AgentRecord:
    host_id: str
    cli: str
    session_id: str
    agent_id: str
    parent_agent_id: Optional[str]
    frontiers: Mapping[str, Frontier]   # source -> latest applied frontier

    def winning(self, grace_s: float = DEFAULT_GRACE_S) -> Tuple[str, Frontier]:
        """Pick the effective (source, frontier) pair. Pure function of event data."""
        items = list(self.frontiers.items())
        freshest = max(_parse_ts(f.ts) for _, f in items)
        candidates = [
            (SOURCE_PRECEDENCE.get(src, 0), _parse_ts(f.ts), f.seq, src)
            for src, f in items
            if (freshest - _parse_ts(f.ts)).total_seconds() <= grace_s
        ]
        candidates.sort()
        best_src = candidates[-1][3]
        return best_src, self.frontiers[best_src]

    @property
    def activity(self) -> str:
        return self.winning()[1].activity

    def freshest_ts(self) -> str:
        # tie-break by the raw string so equal instants in different RFC3339
        # spellings resolve order-invariantly
        return max(self.frontiers.values(), key=lambda f: (_parse_ts(f.ts), f.ts)).ts


@dataclass(frozen=True)
class ReducerState:
    agents: Mapping[AgentKey, AgentRecord]


def initial_state() -> ReducerState:
    return ReducerState(agents=MappingProxyType({}))


def reduce(state: ReducerState, ev: RawEvent) -> ReducerState:
    activity = normalize(ev.cli, ev.kind)
    if activity is None:
        return state  # no activity signal — state untouched

    akey = agent_key(ev)
    rec = state.agents.get(akey)
    prev = rec.frontiers.get(ev.source) if rec else None
    if prev is not None:
        if ev.seq < prev.seq:
            return state  # stale within this stream
        if ev.seq == prev.seq and (ev.ts, ev.kind) <= (prev.ts, prev.kind):
            return state  # duplicate (idempotent) or deterministic tie-break loss

    frontier = Frontier(activity=activity, seq=ev.seq, ts=ev.ts, kind=ev.kind)
    new_frontiers = dict(rec.frontiers) if rec else {}
    new_frontiers[ev.source] = frontier
    # parent_agent_id is an identity FACT, not state: merge order-invariantly.
    # Conflicting non-null claims are an adapter bug; min() keeps it deterministic.
    claims = [p for p in ((rec.parent_agent_id if rec else None), ev.parent_agent_id) if p]
    parent = min(claims) if claims else None
    new_rec = AgentRecord(
        host_id=ev.host_id, cli=ev.cli, session_id=ev.session_id, agent_id=ev.agent_id,
        parent_agent_id=parent,
        frontiers=MappingProxyType(new_frontiers),
    )
    new_agents = dict(state.agents)
    new_agents[akey] = new_rec
    return ReducerState(agents=MappingProxyType(new_agents))


def reduce_all(events: Iterable[RawEvent]) -> ReducerState:
    state = initial_state()
    for ev in events:
        state = reduce(state, ev)
    return state


# ---- view / liveness derivation (time-dependent, kept out of the reducer) ----

def derive_liveness(last_ts: str, now: datetime, *, connected: bool = True,
                    stale_after_s: float = 30.0,
                    disconnected_after_s: float = 120.0) -> str:
    if not connected:
        return "disconnected"
    ts = _parse_ts(last_ts)
    if ts == _EPOCH:
        return "unknown"
    age = (now - ts).total_seconds()
    if age < 0:
        age = 0.0  # clock-skew tolerance: future timestamps read as "now"
    if age >= disconnected_after_s:
        return "disconnected"
    if age >= stale_after_s:
        return "stale"
    return "live"


def view(state: ReducerState, now: datetime, *,
         connected_sessions=None,
         stale_after_s: float = 30.0,
         disconnected_after_s: float = 120.0,
         grace_s: float = DEFAULT_GRACE_S) -> List[dict]:
    """Avatar view: one row per agent with effective activity + derived liveness.

    connected_sessions, when given, must be a set of (host_id, cli, session_id)
    STRING 3-TUPLES; anything else raises TypeError (passing bare session-id
    strings would otherwise silently mark every agent disconnected).
    """
    if connected_sessions is not None:
        for entry in connected_sessions:
            if not (isinstance(entry, tuple) and len(entry) == 3
                    and all(isinstance(p, str) for p in entry)):
                raise TypeError(
                    "connected_sessions must contain (host_id, cli, session_id) "
                    f"string 3-tuples, got {entry!r}")
    rows = []
    for a in state.agents.values():
        connected = True
        if connected_sessions is not None:
            connected = (a.host_id, a.cli, a.session_id) in connected_sessions
        src, frontier = a.winning(grace_s)
        rows.append({
            "host_id": a.host_id, "cli": a.cli, "session_id": a.session_id,
            "agent_id": a.agent_id, "parent_agent_id": a.parent_agent_id,
            "activity": frontier.activity,
            # liveness keys off the freshest observation from ANY source — the
            # agent is demonstrably alive even if the winning source lags.
            "liveness": derive_liveness(a.freshest_ts(), now, connected=connected,
                                        stale_after_s=stale_after_s,
                                        disconnected_after_s=disconnected_after_s),
            "last_seq": frontier.seq, "last_ts": frontier.ts, "last_source": src,
        })
    rows.sort(key=lambda r: (r["host_id"], r["cli"], r["session_id"], r["agent_id"]))
    return rows
