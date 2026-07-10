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

## Phase 0 exhaustive review (2026-07-10)

After Phase 0 shipped (28 tests green), a 30-agent adversarial review (6 lenses: reducer
correctness, tooling/packaging, docs↔code, real-transcript reality check, Claude-hooks ground
truth, design/security) produced 45 findings; 41 survived adversarial verification. The key
corrections, all applied the same day:

1. **`seq` redefined as source-scoped** (the review's central critical). Hooks and the tailer are
   independent observers that can never share a numbering; the original session-scoped `seq` +
   "hook wins same seq" was incoherent, and was *reproduced* mis-reporting a stale tailer pulse over
   a real hook `Stop`. New model: `seq` per `(host, cli, session, source)` stream; reducer keeps a
   frontier per (agent, source) and merges by precedence within a 10 s grace window (event
   timestamps only — replay stays deterministic). This also fixed concurrent-subagent seq
   collisions, removed the unbounded `_seq_source` dedup map (state is now O(agents × sources)),
   and eliminated the same-seq done-downgrade.
2. **`sanitize_meta` made recursive + bounded** — nested/list-nested prompts and secrets previously
   survived ingest; strings are now capped, depth/size bounded, key aliases (NFKC/casefold/strip)
   caught.
3. **Tailer fidelity documented honestly**: real transcripts are silent during permission waits
   (measured gaps to ~292 s), so `waiting`/`blocked` are hook-only for Claude. Tailer stays the boot
   default; the UI/doctor must nudge "install hooks to see waiting."
4. **Tailer `seq` derivation specified**: a tailer-minted strictly-increasing per-stream ordinal
   with the byte-offset resume cursor persisted alongside it (real transcripts have `uuid`/
   `requestId` but no ordinal). A follow-up Codex pass caught that using the raw byte offset *as*
   the seq would make post-rotation records permanently rejectable — hence ordinal + cursor, with
   forward renumbering after rescans.
5. **Doctor made glob-based and env-aware**: every declared session dir was structurally wrong
   (codex nests `YYYY/MM/DD/rollout-*.jsonl`, grok per-session dirs, gemini `<hash>/chats/`);
   hermes is hook-capable via a plugin dir (was marked hook-less); each CLI's own home-override
   env var (`CLAUDE_CONFIG_DIR`, `CODEX_HOME`, …) is honored.
6. **Hook table verified against current docs**: SubagentStart/PermissionRequest/StopFailure/
   PostToolUseFailure/SessionEnd/PreCompact all exist; `Notification` is multiplexed → composite
   kinds (`Notification:<subtype>`); `AskUserQuestion` handled as an adapter-minted composite kind
   (robust whether or not it is a native event name); `StopFailure → blocked` makes the `blocked`
   state reachable; `SessionEnd → done` added.

Rejected review suggestions (with reasons): mapping `TaskCreated/TaskCompleted` to activity states
(a completed *task* does not mean the *agent* is done — would fabricate `done`).

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
