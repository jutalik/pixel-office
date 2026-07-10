# Telemetry Contract (Phase 0 — freeze before any dashboard code)

Everything downstream (tailer, hooks, store, WebSocket protocol, avatars) depends on this. It is
frozen first, on purpose: a Codex review showed that deferring it forces a rewrite once multi-CLI and
reconnect support arrive. Changes here are versioned via `schema_version`.

> **Revision 2026-07-10** (pre-release, after the Phase-0 multi-agent review): `seq` redefined as
> **source-scoped**, cross-source merge moved to per-(agent, source) frontiers with a grace window,
> and meta sanitization made recursive + bounded. See `docs/DECISIONS.md` for the findings that
> forced each change.

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
  "seq":            123,         // SOURCE-SCOPED ordinal — see below
  "ts":             "RFC3339",   // source timestamp (clock-skew tolerated downstream)
  "source":         "hook",      // hook | tailer
  "source_confidence": "high",   // derived from source when omitted: hook=high, tailer=low
  "kind":           "PreToolUse", // lifecycle name; may be an adapter-minted COMPOSITE kind
  "meta":           { }          // metadata ONLY — see §5 (no prompts/args/secrets/file contents)
}
```

**Identity, not pane-id.** Presence and history key on
`(host_id, cli, session_id, agent_id)` — never on a terminal pane/tab id, which is ephemeral and
breaks across restarts, concurrent sessions, and remote hosts.

**`seq` is minted by the adapter and scoped to ONE source stream.** Hooks and the tailer are
independent observers of the same session; they can never agree on a shared numbering, so the
contract does not pretend they can:

- `seq` is monotonic **within `(host_id, cli, session_id, source)`** — strictly increasing per
  stream, 0-based allowed, gaps allowed (a tailer may not see every event).
- The **tailer** mints `seq` as a strictly-increasing per-stream ordinal it maintains itself; the
  byte-offset resume cursor is persisted *alongside* it, never used *as* it. After a truncation or
  rotation rescan the tailer **renumbers forward** from its watermark — it never re-uses or goes
  below already-minted seqs, so post-rotation records are never rejected by the reducer's frontier.
- The **hook receiver** assigns an arrival ordinal per `(host, cli, session, source)` stream.
- `seq` values from different sources are **never compared**; cross-source reconciliation happens
  at the reducer level (§3). There is no cross-agent global order in `seq` — order the UI by `ts`.

**Sessions without a native id.** If a source cannot supply the CLI's own `session_id`, the adapter
mints a synthetic one (`synthetic:<cli>-<start-ts>-<hash>`); if a later event carries the native id,
the adapter re-keys (synthetic → native) before emitting further events.

## 2. Normalized state (what an avatar shows)

The reducer maps raw `kind` → one **activity** state, plus **liveness** derived from time/connection:

- activity: `working` · `waiting` · `blocked` · `done`
- liveness: `live` · `stale` (no events past a TTL) · `disconnected` (source/transport gone) · `unknown`

There is no `idle` event — idle is `stale` liveness. `done` is only ever set by a real terminal
event; the reducer must **never fabricate `done`**. `blocked` = the agent died on an error and needs
a human (e.g. Claude `StopFailure`).

**Fidelity is per (cli, source), and the UI must be honest about it.** Measured against real
transcripts (2026-07-10): Claude Code writes **nothing** to its transcript while blocked on a
permission/question prompt (observed silent gaps up to ~292 s), so:

| cli | tailer can produce | hooks can produce |
|---|---|---|
| claude | `working`, `done` (+liveness) | full table incl. `waiting`, `blocked` |

`waiting` — the single most actionable state ("this agent needs me") — is **hook-only** for Claude.
Tailer-default mode is still the right boot default (zero install), but the UI/doctor must surface
"install hooks to see waiting" rather than silently showing `working`.

## 3. Reducer (deterministic, replay-tested)

`reduce(state, raw_event) -> state`. Pure and deterministic: the same event MULTISET always yields
the same state, regardless of arrival order. Ships with **golden/replay tests**.

- State per agent = one **frontier per source**: the latest applied `(activity, seq, ts, kind)` from
  that stream. Within a stream, latest `seq` wins; equal `seq` (buggy adapter) resolves
  deterministically by `(ts, kind)`. State size is **O(agents × sources)** — no per-seq history.
- The **effective activity** merges frontiers: among frontiers within `GRACE` (default 10 s,
  compared between **event timestamps** — never wall clock) of the freshest frontier, the
  highest-precedence source wins (`hook > tailer`). A dead hook stream ages out of the grace window
  and the tailer takes over automatically; a stale tailer pulse can never override a fresher hook
  terminal state.
- **Composite kinds**: `normalize()` is a flat per-CLI lookup. Events whose signal lives in sibling
  fields are disambiguated by the adapter before normalization — e.g. Claude `PreToolUse` with
  `tool_name == "AskUserQuestion"` is emitted as kind `AskUserQuestion`; `Notification` subtypes are
  emitted as `Notification:<subtype>` (bare `Notification` remains a conservative `waiting` fallback).
- The same reducer is reused by the tailer (Phase 1), hooks (Phase 2), and every multi-CLI adapter
  (Phase 3) — **one normalize table per CLI**, one merge semantics for everyone.

## 4. Dedup, precedence, ordering
- **Dedup** happens per stream: an event at or below its stream frontier's `seq` is dropped
  (equal-`seq` conflicts resolve by the deterministic `(ts, kind)` tie-break).
- **Cross-source precedence** is the reducer's frontier merge (§3) — there is no same-`seq`
  cross-source rule, because independent sources never share a numbering.
- **Ordering:** apply by stream `seq`; out-of-order arrivals within a stream are handled by
  latest-seq-wins. Cross-stream ordering uses `ts` only inside the grace-window merge.
- **Clock trust:** the frontier merge trusts event timestamps, so a source with a grossly
  future-skewed clock shadows other sources until the skew passes. Adapters therefore SHOULD mint
  `ts` from the same clock family (the CLI's own machine clock); liveness already clamps future
  timestamps to "now".
- **Truncation/rotation** (tailer): a file shrinking below the resume cursor → reset the cursor;
  inode/mtime change → rescan. Resume only past the last complete newline-terminated record. The
  tailer's minted `seq` continues forward from its watermark across rescans (§1), so re-read
  records get fresh seqs and the stream frontier keeps advancing — nothing is silently rejected.

## 5. Security & privacy defaults
- **Loopback-only** receiver, bound to `127.0.0.1`, with a per-run **bearer token** (endpoint file).
- **Metadata only.** Never record prompts, tool arguments, secrets, tokens, or file contents.
  `sanitize_meta` is **recursive and bounded**: forbidden keys are dropped at any depth (after
  NFKC + casefold + strip normalization, so aliases like `"prompt "`/`toolInput` are caught),
  strings are truncated to ≤256 chars (marker included), oversized keys/bigints/non-finite floats
  are dropped, container depth/size is capped, and unexpected types are dropped. Sanitization runs
  **exactly once, at the ingest boundary**, and the append-only store
  persists the **sanitized** form — replay reads exactly what live ingest produced, and the store
  never contains content.
- Any CLI-originated text rendered in the UI is **escaped**; the dashboard sets a strict **CSP**.
- **Bounded** everywhere: reducer state is O(agents × sources); meta values are size-capped;
  retention/backpressure at the store drops oldest with a visible badge rather than growing forever.
- Telemetry **fails open** (never blocks the CLI or product); privileged actions **fail closed**.

## 6. Transport (snapshot + ordered deltas)
- On connect: the server sends a full **snapshot** of current per-agent state, then **ordered deltas**.
- On reconnect: re-snapshot, then resume deltas — the client never assumes continuity across a gap.
- Deltas are **semantic** (state + destination room/slot), never raw pixel coordinates.
