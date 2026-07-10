# Decisions

A running log of design decisions and *why*. Newest context at the bottom.

## How these were made
The design was pressure-tested through a multi-model deliberation:
- **Claude** — framing, synthesis, and the auth/telemetry research (studied Orca's implementation).
- **Codex (gpt-5.6-sol)** — robustness and sequencing review.
- **Grok-4** — lightweight/UX review.

(Gemini and ChatGPT were also invited but were unreachable at the time.) Where the reviewers
disagreed, the resolution and reasoning are recorded below.

## Locked decisions

1. **Local-first execution.** The scaffolded product runs on the user's machine. "Live promotion"
   is delegated to the user's own agents via an **env-adaptive deploy playbook** (detect
   docker/domain/tunnel/localhost → the agent deploys accordingly).
2. **Scaffold = instrumentation-complete skeleton + agents flesh out features.** The skeleton's job
   is to guarantee that telemetry and the office work regardless of what agents build on top.
3. **Auth = delegate to each CLI's native login.** No token storage or refresh. Subscription OAuth
   and API key both work because the CLI handles them.
4. **Telemetry is two-tier** (see ARCHITECTURE): tailer default, hooks as an opt-in upgrade; both
   feed one reducer.
5. **Avatar state is server-derived** and honest — an avatar moves only on a real status change.

## Resolved disagreements

| Topic | Codex | Grok | Resolution |
|---|---|---|---|
| Default telemetry mode | hooks-primary + repair | **tailer default, hooks opt-in** | **Grok** — degrade-first: boot on the always-works tailer, offer a one-click "live mode" (hooks) upgrade. Lowest first-run failure. |
| Renderer | Canvas2D + atlas | **DOM/CSS sprites** | **Grok (DOM) default**, Canvas2D as a documented escalation past ~10 avatars. Simpler, accessible, mobile-friendly. |
| PWA / mobile timing | **only after reachability solved** | eager PWA | **Codex** — a local-first app is unreachable from a phone until tunneled, so mobile monitoring is coupled to the deploy path; ship a PWA that caches the last snapshot and clearly labels stale/unreachable. |

## The structural move (both reviewers' "one thing to change")
Split the skeleton into a **robust headless core** (product + telemetry + privileged actions, each an
isolated failure domain) and an **optional presentation overlay** (the game). This is the single
biggest revision to the original single-file-backend plan.

## Codex sequencing review (2026-07-10)
- **Freeze the telemetry/identity/security contract in Phase 0** before any dashboard code, or
  multi-CLI + reconnect will force a rewrite of the tailer, store, and ws protocol.
- **Pane-id is not a durable identity.** Restarts, concurrent sessions, subagents, remote hosts, and
  hook+tailer duplicates break presence/history. Introduce `host_id, cli, session_id, agent_id,
  parent_agent_id`, monotonic `seq`, and deterministic dedup before the first dashboard protocol.
  (This is a known weak spot in Orca, which keys live status on an ephemeral pane id.)
- **Split Phase 1** into a minimal first-avatar demo (1a) and a durability pass (1b).

## Auth landscape (research summary)
- Orca actively manages accounts for only **Claude and Codex** (subscription OAuth only; API keys are
  detected and rejected), using a "materialize creds into the CLI's config dir + redirect via env var
  (`CLAUDE_CONFIG_DIR`/`CODEX_HOME`)" pattern. Every other CLI it just launches, delegating to native
  login and only *reading* session files for usage.
- The dominant ecosystem pattern (Claude Squad, Conductor, Crystal, uzi, omnara) is **delegate-to-
  native-login + isolate the workspace (git worktree), not the account**. Cloud platforms that must
  run the CLI remotely (Terragon) or reject consumer subscriptions (Warp) are the credential-managing
  outliers. → Pixel Office delegates auth; it isolates by config-dir only where multi-account rotation
  is explicitly wanted.
