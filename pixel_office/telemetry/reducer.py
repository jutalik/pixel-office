"""Deterministic reducer: raw events -> current per-agent state.

Invariants (see docs/TELEMETRY-CONTRACT.md):
- Latest seq wins per agent, so the FINAL state is independent of arrival order.
- Dedup by (host,cli,session,seq); when hook and tailer describe the same seq the
  hook wins (higher SOURCE_PRECEDENCE).
- Unknown kinds are ignored; `done` is only ever set by a real terminal event.

Liveness (stale/disconnected) is time-dependent and therefore derived in a view
function, kept out of the reducer so replay stays deterministic.
"""
from __future__ import annotations

from dataclasses import dataclass, field, replace
from datetime import datetime, timezone
from typing import Dict, Iterable, List, Optional

from .contract import (
    AgentKey, RawEvent, SeqKey, SOURCE_PRECEDENCE, agent_key, seq_key,
)
from .normalize import normalize


@dataclass(frozen=True)
class AgentState:
    host_id: str
    cli: str
    session_id: str
    agent_id: str
    activity: str
    last_seq: int
    last_ts: str
    last_source: str
    parent_agent_id: Optional[str] = None


@dataclass(frozen=True)
class ReducerState:
    agents: Dict[AgentKey, AgentState] = field(default_factory=dict)
    # winning source per (host,cli,session,seq) for dedup + precedence
    _seq_source: Dict[SeqKey, str] = field(default_factory=dict)


def initial_state() -> ReducerState:
    return ReducerState(agents={}, _seq_source={})


def reduce(state: ReducerState, ev: RawEvent) -> ReducerState:
    sk = seq_key(ev)
    prev_src = state._seq_source.get(sk)
    if prev_src is not None and SOURCE_PRECEDENCE[ev.source] <= SOURCE_PRECEDENCE[prev_src]:
        # already have an equal-or-higher precedence source for this seq
        return state

    activity = normalize(ev.cli, ev.kind)
    if activity is None:
        # no activity signal: don't claim the seq, leave state untouched
        return state

    new_seq_source = dict(state._seq_source)
    new_seq_source[sk] = ev.source

    akey = agent_key(ev)
    cur = state.agents.get(akey)
    # latest-seq-wins; equal seq only reaches here when the new source outranks the
    # one already applied, in which case it should override.
    if cur is not None and ev.seq < cur.last_seq:
        return replace(state, _seq_source=new_seq_source)

    new_agent = AgentState(
        host_id=ev.host_id, cli=ev.cli, session_id=ev.session_id, agent_id=ev.agent_id,
        activity=activity, last_seq=ev.seq, last_ts=ev.ts, last_source=ev.source,
        parent_agent_id=ev.parent_agent_id or (cur.parent_agent_id if cur else None),
    )
    new_agents = dict(state.agents)
    new_agents[akey] = new_agent
    return ReducerState(agents=new_agents, _seq_source=new_seq_source)


def reduce_all(events: Iterable[RawEvent]) -> ReducerState:
    state = initial_state()
    for ev in events:
        state = reduce(state, ev)
    return state


# ---- view / liveness derivation (time-dependent, kept out of the reducer) ----

def _parse_ts(ts: str) -> datetime:
    dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


def derive_liveness(agent: AgentState, now: datetime, *, connected: bool = True,
                    stale_after_s: float = 30.0,
                    disconnected_after_s: float = 120.0) -> str:
    if not connected:
        return "disconnected"
    try:
        age = (now - _parse_ts(agent.last_ts)).total_seconds()
    except ValueError:
        return "unknown"
    if age < 0:
        age = 0.0  # clock-skew tolerance
    if age >= disconnected_after_s:
        return "disconnected"
    if age >= stale_after_s:
        return "stale"
    return "live"


def view(state: ReducerState, now: datetime, *, connected_sessions=None, **kw) -> List[dict]:
    """Avatar view: one row per agent with activity + derived liveness."""
    rows = []
    for a in state.agents.values():
        connected = True
        if connected_sessions is not None:
            connected = (a.host_id, a.cli, a.session_id) in connected_sessions
        rows.append({
            "host_id": a.host_id, "cli": a.cli, "session_id": a.session_id,
            "agent_id": a.agent_id, "parent_agent_id": a.parent_agent_id,
            "activity": a.activity,
            "liveness": derive_liveness(a, now, connected=connected, **kw),
            "last_seq": a.last_seq, "last_ts": a.last_ts, "last_source": a.last_source,
        })
    rows.sort(key=lambda r: (r["host_id"], r["cli"], r["session_id"], r["agent_id"]))
    return rows
