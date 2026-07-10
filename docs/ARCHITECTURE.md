# Architecture

## The one big idea: a robust headless **core** + an optional presentation **overlay**

Two independent reviewers (Codex, Grok) converged on the same structural move, from opposite
directions:

- **Codex:** split the single-file backend into isolated failure domains so one bad telemetry
  event or a locked write can't take down the product and the office together.
- **Grok:** make the pixel office a pure client-side overlay you can disable with one env var, so
  the product ships even without any game code.

Same conclusion: **separate the durable core from the delight layer.**

```
core/  (one process, four isolated failure domains, separate write paths)
├── product/     the user's actual product (FastAPI + SQLite): /health /ready, KPI surface
├── telemetry/   event ingest (hooks + tailer) → reducer → state; fails OPEN
├── control/     privileged actions (deploy/spend/approvals): fails CLOSED, audited, token-gated
└── dashboard/   serves the office view + the WebSocket feed
overlay/  (optional, PO_OVERLAY=off) the pixel office: DOM/CSS avatars, honesty-locked
tooling/  po doctor · po repair · CLI adapters (install→detect→observe→uninstall)
```

## Telemetry: two tiers, one reducer

Activity is captured two ways, and **both feed a single deterministic reducer** (so hooks and the
tailer can never disagree about what an avatar is doing):

1. **Primary — hooks (opt-in upgrade).** A loopback HTTP receiver + per-CLI managed hook installers.
   CLIs POST lifecycle events; the receiver returns immediately (fail-open) and normalizes them.
   Highest fidelity: tool- and subagent-level granularity.
2. **Fallback — session-file tailer (default).** Byte-offset incremental tailing of each CLI's own
   session logs. Works for any CLI, needs no install → **zero first-run failure**. Lower fidelity
   (retrospective pulses), so it is the default that "always works," with hooks as a one-click upgrade.

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
