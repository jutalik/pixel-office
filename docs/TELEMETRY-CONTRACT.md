# Telemetry Contract (Phase 0 — freeze before any dashboard code)

Everything downstream (tailer, hooks, store, WebSocket protocol, avatars) depends on this. It is
frozen first, on purpose: a Codex review showed that deferring it forces a rewrite once multi-CLI and
reconnect support arrive. Changes here are versioned via `schema_version`.

## 1. Raw event (append-only, versioned)

A raw event is what a source (tailer or hook) emits. It is stored append-only and never mutated.

```jsonc
{
  "schema_version": 1,
  "host_id":        "string",   // stable per machine
  "cli":            "claude",   // claude | codex | grok | gemini | ...
  "session_id":     "string",   // the CLI's own session identity (durable, not a pane id)
  "agent_id":       "string",   // this agent/subagent within the session
  "parent_agent_id":"string|null", // set for subagents/workflows → tree structure
  "seq":            123,         // monotonic per (host_id,cli,session_id); orders events, dedups
  "ts":             "RFC3339",   // source timestamp (clock-skew tolerated downstream)
  "source":         "hook",      // hook | tailer
  "source_confidence": "high",   // high (hook) | low (tailer retrospective)
  "kind":           "PreToolUse", // raw lifecycle name from the source
  "meta":           { }          // metadata ONLY — see §5 (no prompts/args/secrets/file contents)
}
```

**Identity, not pane-id.** Presence and history key on
`(host_id, cli, session_id, agent_id)` — never on a terminal pane/tab id, which is ephemeral and
breaks across restarts, concurrent sessions, and remote hosts.

## 2. Normalized state (what an avatar shows)

The reducer maps raw `kind` → one **activity** state, plus **liveness** derived from time/connection:

- activity: `working` · `waiting` · `blocked` · `done`
- liveness: `unknown` · `stale` (no events past a TTL) · `disconnected` (source/transport gone)

There is no `idle` event — idle is `stale` liveness. `done` is only ever set by a real terminal
event; the reducer must **never fabricate `done`**.

## 3. Reducer (deterministic, replay-tested)

`reduce(state, raw_event) -> state`. Pure and deterministic: the same event stream always yields the
same state. Ships with **golden/replay tests** over recorded fixtures. This same reducer is reused by
the tailer (Phase 1), the hooks path (Phase 2), and every multi-CLI adapter (Phase 3) — one source of
truth for "what is this agent doing right now."

## 4. Dedup, precedence, ordering
- **Dedup** by `(host_id, cli, session_id, seq)`.
- **Precedence:** when hook and tailer describe the same `seq`, **hook wins** (higher confidence).
- **Ordering:** apply by `seq`; out-of-order arrivals are buffered briefly, then reconciled.
- **Truncation/rotation** (tailer): a file shrinking below the last offset → reset offset; inode/mtime
  change → rescan. Resume only past the last complete newline-terminated record.

## 5. Security & privacy defaults
- **Loopback-only** receiver, bound to `127.0.0.1`, with a per-run **bearer token** (endpoint file).
- **Metadata only.** Never record prompts, tool arguments, secrets, tokens, or file contents by
  default. `meta` carries counts/names/booleans/durations — not content.
- Any CLI-originated text rendered in the UI is **escaped**; the dashboard sets a strict **CSP**.
- **Bounded** retention and backpressure; drop-oldest with a visible badge rather than unbounded growth.
- Telemetry **fails open** (never blocks the CLI or product); privileged actions **fail closed**.

## 6. Transport (snapshot + ordered deltas)
- On connect: the server sends a full **snapshot** of current per-agent state, then **ordered deltas**.
- On reconnect: re-snapshot, then resume deltas — the client never assumes continuity across a gap.
- Deltas are **semantic** (state + destination room/slot), never raw pixel coordinates.
