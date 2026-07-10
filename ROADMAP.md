# Roadmap

Dependency-ordered build plan. Principles baked in: **crux-first** (telemetry),
**degrade-first** (tailer before hooks), **earliest honest win** (first avatar ASAP),
**core before overlay**, product/control/mobile last.

This order was validated by a Codex review (2026-07-10). Its key correction: **freeze the
telemetry/identity/security contract in Phase 0 before any dashboard code**, or multi-CLI
and reconnect support will force a rewrite of the tailer, store, and WebSocket protocol.
Phase 1 was split into a minimal demo (1a) and a hardening pass (1b).

## Cross-cutting invariants (hold from Phase 0 onward)
- Append-only, versioned raw events; a **deterministic reducer** with replay/golden tests.
- Durable identity, not pane-id: `host_id, cli, session_id, agent_id, parent_agent_id`, monotonic `seq`.
- Hook/tailer **deduplication + precedence**; explicit `unknown | stale | disconnected` states.
- Telemetry **fails open**; privileged actions **fail closed** (audit-before-action, single-use tokens).
- Loopback-only + bearer auth by default; CSP + escaping for any CLI-originated text.
- **Never record** prompts, tool arguments, secrets, or file contents by default (metadata only).
- Bounded retention/backpressure; clock-skew tolerance; reconnect = snapshot then ordered deltas.

## Phase 0 — Contract & harness (freeze first)
Define and freeze the telemetry event envelope, identity model, normalized state machine, reducer
semantics, snapshot+delta transport, schema versioning, and security defaults. Ship a **replay
harness** with recorded fixtures. Stubs for the 4-domain core (product / telemetry / control /
dashboard), one SQLite in WAL. `po doctor` capability matrix.
**Exit:** contract documented + reducer passes golden replay tests; `po doctor` prints the matrix.

## Phase 1a — Minimal first-avatar slice
One Claude session → tailer → normalized event → single in-memory state → one browser client →
a CSS state change on one avatar. Keep truncation-safety and `stale/disconnected` from day one;
defer SQLite history, multi-pane mapping, movement, and rotation handling.
**Exit:** run Claude in a terminal → one avatar reacts, live.

## Phase 1b — Durable tailing & hardening
Byte-offset + mtime/size + newline-boundary resume (truncation→reset, rotation→rescan); reconnect
resync; persistence; multi-pane mapping; retention/backpressure.
**Exit:** survives restarts, rotation, reconnect without losing or duplicating state.

## Phase 2 — Hooks upgrade (opt-in, same CLI)
`po hooks install` (managed hook script) → live per-event push with tool/subagent granularity,
fail-open, verified by `po doctor`, clean uninstall. **Reuses the Phase 0 reducer.**
**Exit:** live mode shows PreToolUse/PostToolUse/subagent detail; disabling reverts to the tailer.

## Phase 3 — Multi-CLI adapters
codex, grok, gemini behind one contract: `install → detect → observe → uninstall`. Hook-capable →
hooks; hook-less → tailer. **Reuses the contract + conformance tests.**
**Exit:** 3+ CLIs appear as avatars (mixed hook/tailer); a missing CLI never blocks bootstrap.

## Phase 4 — Game overlay (DOM/CSS, disable-able)
Rooms, movement, speech bubbles; honesty-locked; LOD / FPS caps / pause-on-hidden / reduced-motion;
`PO_OVERLAY=off` yields the headless core. Canvas2D only as a documented escalation at >~10 avatars.
**Exit:** pleasant office on low-spec hardware; env var disables all game code.

## Phase 5 — Product skeleton + conversational init
Instrumented FastAPI + SQLite product skeleton (inside the 4-domain split). `po new` = conversation
+ editable cards + plain-language **charter confirmation** → manifest/seed (api-service /
data-pipeline / chat-product templates).
**Exit:** `po new` → an already-instrumented product; the charter step prevents a broken seed.

## Phase 6 — Control plane & deploy playbook
Approvals/budget (fail-closed, audit, single-use expiring capability tokens). Env-adaptive deploy
playbook (localhost / docker / tunnel) for agent-driven live promotion.
**Exit:** risky actions gated + audited; an agent promotes per the detected environment.

## Phase 7 — Mobile / PWA
One responsive app, read-only monitor mode, same ws feed with reduced rendering, detail sheets.
PWA caches shell + last snapshot. Reachability is **coupled to deploy/tunnel** (a phone cannot reach
localhost), so mobile monitoring becomes available only after live promotion.
**Exit:** phone shows live status once promoted; stale/unreachable clearly labeled.

## What can run in parallel (after the Phase 0 contract freezes)
`po doctor`; dashboard shell; recorded telemetry fixtures; the hook installer; multi-CLI adapter
research; packaging/CI. Product templates, overlay art, control actions, and PWA work proceed
independently **only against the frozen interfaces**.
