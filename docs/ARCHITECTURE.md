# Architecture

## The one big idea: a robust headless **core** + an optional presentation **overlay**

Two independent reviewers (Codex, Grok) converged on the same structural move, from opposite
directions:

- **Codex:** split the single-file backend into isolated failure domains so one bad telemetry
  event or a locked write can't take down the product and the office together.
- **Grok:** make the pixel office a pure client-side overlay you can disable with one env var, so
  the product ships even without any game code.

Same conclusion: **separate the durable core from the delight layer.** The four
domains below are a conceptual model of the responsibilities; the actual module
layout (right column) realizes them without a literal `core/` package.

| domain (concept) | responsibility | where it lives in `pixel_office/` |
|---|---|---|
| **telemetry** | event ingest (hooks + tailer) → reducer → state; fails OPEN | `telemetry/` + `adapters/` (one descriptor per CLI) |
| **control** | privileged actions (deploy/spend/approvals/budget): fails CLOSED, audited, token-gated | `control/` |
| **dashboard** | serves the office view + the WebSocket feed | `server.py` |
| **product** | the user's actual product (FastAPI + SQLite, instrumented) | a **scaffolded template** (`scaffold/`) rendered into the user's *new* project — not a module of this repo |
| overlay (optional, `PO_OVERLAY=off`) | the pixel office: DOM/CSS avatars, honesty-locked | `static/` |
| tooling | `po doctor` · `po hooks` · `po new` · `po deploy` | `doctor.py` · `hooks.py` · `cli.py` |

Failure isolation is by discipline (telemetry fails open, control fails closed;
the tailer/hook receiver never raise into the web loop), not by separate OS
processes — this is a single local process.

## Telemetry: two tiers, one reducer

Activity is captured two ways, and **both feed a single deterministic reducer** that keeps one
frontier per (agent, source) and merges them by source precedence within a freshness grace window —
so mixed hook/tailer input always yields one honest answer per avatar:

1. **Primary — hooks (opt-in upgrade).** A loopback HTTP receiver + per-CLI managed hook installers.
   CLIs POST lifecycle events; the receiver returns immediately (fail-open) and normalizes them.
   Highest fidelity: tool- and subagent-level granularity.
2. **Fallback — session-file tailer (default).** Byte-offset incremental tailing of each CLI's own
   session logs. Works for any CLI, needs no install → **zero first-run failure**. Lower fidelity
   (retrospective pulses), so it is the default that "always works," with hooks as a one-click upgrade.

**Fidelity caveats (measured):** Claude's transcript is *silent* while the agent waits on a
permission/question prompt, so tailer-only mode can never show `waiting` — the "this agent needs
me" signal arrives with the hooks upgrade. The UI and `po doctor` say so explicitly instead of
letting a blocked agent read as `working`. Additionally, transcript **flush cadence varies by
harness**: vanilla Claude Code writes per API response (seconds), but pooled/wrapped setups can
buffer a whole *turn* (measured 17+ minutes on a long agentic turn) — during which the tailer
honestly reports staleness while the agent is hard at work. Hooks fire live regardless of flush
cadence, which is why they are the primary tier.

Avatar state is **server-derived** (a pure view function, no coordinate database) and pushed over a
WebSocket as **semantic deltas** (a state enum + destination, never raw coordinates). See
[`TELEMETRY-CONTRACT.md`](TELEMETRY-CONTRACT.md) for the frozen envelope, identity model, and states.

## Auth: delegate, never store

Users run varied CLIs (Claude, Codex, Grok, Gemini, Hermes…) and sign in however they already do —
subscription OAuth *or* API key. Pixel Office **delegates to each CLI's native login** and stores no
tokens. This is the dominant pattern across the ecosystem (Claude Squad, Conductor, Crystal, uzi, and
Orca's long-tail agents all do it), and it sidesteps the ToS problems of reimplementing provider OAuth.
Per-account isolation (a config-dir env var per account) is added only where multi-account rotation
is actually wanted — it is not required for the single-user default.

## Rendering: light by default

- **DOM/CSS sprites** for the typical 1–8 avatars. No Canvas or WebGL initially.
- Server-authoritative presence; client interpolates between low-rate (~4 Hz) semantic deltas.
- Hard caps: FPS (30 moving / 10–15 settled), pause on hidden tab, honor `prefers-reduced-motion`,
  LOD to a static dot/room on weak devices.
- **Canvas2D** is a documented escalation only past ~10 avatars.

## Mobile

One responsive app (not a second frontend). Phones default to a **read-only monitor mode** on the
same ws feed with rendering reduced; risky actions require deliberate re-auth. Because the app is
local-first, a phone can only reach it once the deploy playbook has set up a tunnel/live URL — so
mobile monitoring is intentionally **coupled to live promotion**.

> **Status (not yet built):** the server currently enforces a **loopback-only** Host/Origin
> allowlist (`127.0.0.1`/`localhost`), so a raw tunnel hostname is rejected as-is. Real
> remote/phone access needs an explicit, authenticated configurable allowlist — future work, not
> shipped. Today, view remotely over a private overlay (e.g. Tailscale) that presents as loopback.
