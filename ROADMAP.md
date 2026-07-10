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
- Durable identity, not pane-id: `host_id, cli, session_id, agent_id, parent_agent_id`; `seq` is
  minted per **source stream** `(host, cli, session, source)` — sources never share a numbering.
- Cross-source merge via per-(agent, source) **frontiers** + grace window (hook > tailer);
  explicit `live | unknown | stale | disconnected` liveness states.
- Telemetry **fails open**; privileged actions **fail closed** (audit-before-action, single-use tokens).
- Loopback-only + bearer auth by default; CSP + escaping for any CLI-originated text.
- **Never record** prompts, tool arguments, secrets, or file contents by default (metadata only).
- Bounded retention/backpressure; clock-skew tolerance; reconnect = snapshot then ordered deltas.

## Phase 0 — Contract & harness (freeze first)
Define and freeze the telemetry event envelope, identity model, normalized state machine, reducer
semantics, snapshot+delta transport, schema versioning, and security defaults. Ship a **replay
harness** with recorded fixtures and the `po doctor` capability matrix. (The product/control/
dashboard domains are named in ARCHITECTURE and laid down from Phase 1a onward; SQLite/WAL arrives
with the Phase 1b store.)
**Exit:** contract documented + reducer passes golden replay tests; `po doctor` prints the matrix.
✅ **Shipped 2026-07-10** (55 tests green), then hardened by a 30-agent adversarial review — see
`docs/DECISIONS.md` "Phase 0 exhaustive review".

## Phase 1a — Minimal first-avatar slice
One Claude session → tailer → normalized event → single in-memory state → one browser client →
a CSS state change on one avatar. Keep truncation-safety and `stale/disconnected` from day one;
defer SQLite history, multi-pane mapping, movement, and rotation handling.
**Exit:** run Claude in a terminal → one avatar reacts, live.
✅ **Shipped 2026-07-10** (`po up`, 80 tests green). Verified end-to-end live: working →
working(tool) → done transitions on a mutating transcript; ws snapshot+delta; headless-browser
screenshot; dogfooded against this repo's own build session (which calibrated the liveness
defaults to 90 s/600 s — a single real Claude API call can exceed 2 minutes). Beyond plan:
same-size rewrite detection (inode+head fingerprint) and per-record fail-open landed early
(Codex review); subagent (sidechain) avatars intentionally deferred to hooks (Phase 2).

## Phase 1b — Durable tailing & hardening
Byte-offset + mtime/size + newline-boundary resume (truncation→reset, rotation→rescan); reconnect
resync; persistence; multi-pane mapping; retention/backpressure.
**Exit:** survives restarts, rotation, reconnect without losing or duplicating state.
✅ **Shipped 2026-07-10** (86 tests green): SessionWatcher tails every active session behind the
glob with durable per-file cursors/watermarks (atomic JSON in `~/.pixel-office/state`, restart
re-emits nothing, seq stays forward-only); backpressure at the file level (max_files=32, 48 h
active window) and byte level (4 MB/poll, drained back-to-back with `sleep(0)` yields so a big
cold-start never blocks serving); rewrite detection via inode + head fingerprint. Measured
harness caveat recorded in ARCHITECTURE: pooled setups can flush transcripts turn-grained
(17+ min observed) — one more reason hooks are the primary tier.

## Phase 2 — Hooks upgrade (opt-in, same CLI)
`po hooks install` (managed hook script) → live per-event push with tool/subagent granularity,
fail-open, verified by `po doctor`, clean uninstall. **Reuses the Phase 0 reducer.**
**Exit:** live mode shows PreToolUse/PostToolUse/subagent detail; disabling reverts to the tailer.
✅ **Shipped 2026-07-10** (98 tests green). Receiver = POST /hook/{cli} on the dashboard port
(loopback, per-run bearer token via a 0600 endpoint file; auth 403, everything else fails open
204). Installer merges additively into settings.json under an ownership marker — user hooks are
never touched, uninstall is surgical, corrupt settings are refused not clobbered, one reversible
backup per change. Verified live end-to-end: the real installed script POSTed PermissionRequest →
avatar flipped to `waiting` (outranking the tailer), SubagentStart spawned a second avatar with
parent=main, and the script exits 0 with the receiver down. `waiting`/`blocked` — the hook-only
states — are now reachable.

## Phase 3 — Multi-CLI adapters
codex, grok, agy behind one contract: `install → detect → observe → uninstall`. **Reuses the
contract + conformance tests.** (Tailer adapters shipped for codex+grok; hooks remain Claude-only —
per-CLI hook installers are future work, see docs/CLI-MATRIX.md.)
**Exit:** 3+ CLIs appear as avatars (tailer); a missing CLI never blocks bootstrap.
✅ **codex + grok shipped 2026-07-10** (110 tests green). One office now shows claude + codex +
grok avatars together (live-verified: 70 distinct top-level SESSIONS across the three CLIs — one
`main` avatar per session in tailer mode; per-subagent avatars require hooks, Claude only today).
Controlled screenshot of all three with working/done/**waiting**. Each adapter is a ~30-line
`parse_line` reusing the frozen reducer.
Findings that shaped it: grok's real signal is `events.jsonl` (structured, timestamped), NOT
`chat_history.jsonl` (no timestamps) — and because grok logs `permission_requested`, it is the ONE
CLI whose tailer reaches `waiting`. Per-CLI session-id fallback added (grok's file is always
`events.jsonl`, so identity is the parent-dir uuid). Gemini adapter + the hermes hooks-plugin
installer remain to close Phase 3.

## Phase 4 — Game overlay (DOM/CSS, disable-able)
Rooms, movement, speech bubbles; honesty-locked; LOD / FPS caps / pause-on-hidden / reduced-motion;
`PO_OVERLAY=off` yields the headless core. Canvas2D only as a documented escalation at >~10 avatars.
**Exit:** pleasant office on low-spec hardware; env var disables all game code.
✅ **Shipped 2026-07-10** (111 tests green). Per-CLI team rooms; avatars glide between rooms on
state change (CSS transform, no canvas); bob/wave animations gated behind `prefers-reduced-motion`;
honest speech bubbles (shown for the actionable `waiting`/`blocked` states, derived from state —
never prompt text); LOD cap (MAX_RENDER=80 + "+N more");
pause-on-hidden. `PO_OVERLAY=off` serves a plain table on the *same* ws feed. Screenshot verified
(3 rooms, mixed focus/wrapped/needs-you).

## Phase 5 — Product skeleton + conversational init
Instrumented FastAPI + SQLite product skeleton (inside the 4-domain split). `po new` = conversation
+ editable cards + plain-language **charter confirmation** → manifest/seed (api-service /
data-pipeline / chat-product templates).
**Exit:** `po new` → an already-instrumented product; the charter step prevents a broken seed.
✅ **Shipped 2026-07-10** (123 tests green). `po new` (interactive Q&A OR flags), extended manifest
(what/goal/benchmarks/niche/stack/roles) with bounded, injection-safe validation of untrusted input;
plain-language charter confirmation before anything is written; 3 instrumentation-complete templates
(FastAPI+SQLite: /health, /ready, /api/telemetry|funnel|quality|growth, X-App-Token writes, WAL) +
an env-adaptive deploy playbook + Dockerfile. E2E verified: scaffolded a recipebot, its own smoke
test passed, the backend ran and answered instrumentation + enforced write auth (401→200). Codex
caught a code-injection (untrusted name into generated source) and a type-crash — both fixed with
regressions (a payload that would `open()` a sentinel file is proven inert after exec).

## Phase 6 — Control plane & deploy playbook
Approvals/budget (fail-closed, audit, single-use expiring capability tokens). Env-adaptive deploy
playbook (localhost / docker / tunnel) for agent-driven live promotion.
**Exit:** risky actions gated + audited; an agent promotes per the detected environment.
✅ **Shipped 2026-07-10** (136 tests green). `control/approvals.py`: deterministic fail-closed
`classify` (deploy/spend/delete/external_send/prod_change/grant_access), escalate-only UNION
binding (a declared type never shrinks detected risk), single-use approvals that must be explicitly
approved and are claimed atomically under a lock (20-thread test → exactly one winner), inclusive
expiry, audit records holding a salted prompt HASH never the text. `control/deploy.py` + `po deploy`:
detects docker/tunnel(cloudflared·tailscale)/localhost and recommends the least-public reachable
path — live-verified (docker+tailscale → tunnel:tailscale, phone-reachable). All four Codex findings
(claim-without-approval, non-atomic claim, declared-overrides-detected, expiry off-by-one) fixed
with regressions. `classify` is an operator safety-belt, not an adversarial boundary (documented).

## Phase 7 — Mobile / PWA
One responsive app, read-only monitor mode, same ws feed with reduced rendering, detail sheets.
PWA caches shell + last snapshot. Reachability is **coupled to deploy/tunnel** (a phone cannot reach
localhost), so mobile monitoring becomes available only after live promotion.
**Exit:** phone shows live status once promoted; stale/unreachable clearly labeled.
✅ **Shipped 2026-07-10** (137 tests green). One responsive app (single-column rooms + larger touch
targets under 600px, verified by a 390px screenshot); installable PWA (`/manifest.webmanifest`,
`/sw.js` at root scope, `/icon.svg`); the service worker caches the shell and the client persists
the last snapshot to localStorage so reopening shows last-known state instantly (even offline); an
honest banner distinguishes live vs "offline — last-known state", and the SW comment states it never
implies the local office is remotely reachable on its own (reachability comes from `po deploy`).
The office is inherently read-only (no mutation controls), so mobile is safe by construction.

## What can run in parallel (after the Phase 0 contract freezes)
`po doctor`; dashboard shell; recorded telemetry fixtures; the hook installer; multi-CLI adapter
research; packaging/CI. Product templates, overlay art, control actions, and PWA work proceed
independently **only against the frozen interfaces**.
