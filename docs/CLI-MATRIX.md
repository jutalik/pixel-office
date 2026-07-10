# CLI support matrix

What Pixel Office knows about each CLI's telemetry, and how verified it is.
"Verified" = checked against real on-disk data on a live install (2026-07-10).

| CLI | binary | session store | tailer states | hooks | status |
|---|---|---|---|---|---|
| **claude** | `claude` | `~/.claude/projects/*/*.jsonl` (JSONL) | working, done | settings.json | ✅ verified |
| **codex** | `codex` | `~/.codex/sessions/YYYY/MM/DD/rollout-*.jsonl` (JSONL) | working, done | config | ✅ verified |
| **grok** | `~/.grok/bin/grok` | `~/.grok/sessions/<enc-cwd>/<uuid>/events.jsonl` (JSONL) | working, **waiting**, done | config | ✅ verified |
| **agy** (Antigravity) | `~/.local/bin/agy` | `~/.gemini/antigravity-cli/*.db` (**SQLite**) | — | settings | 🟡 provisional |
| **hermes** | `hermes` | — (no session store found) | — | plugin (`~/.hermes/plugins/`) | 🟡 hooks-only |

## Notes

- **grok** is the only CLI whose *tailer* reaches `waiting`: its `events.jsonl`
  logs `permission_requested`/`permission_resolved`. Claude and Codex transcripts
  are silent during approval waits, so for them `waiting`/`blocked` are hook-only.
  Grok's real signal is `events.jsonl`, **not** `chat_history.jsonl` (no timestamps).

- **agy = Antigravity CLI** (Google), the successor to gemini-cli (which Pixel
  Office no longer lists). Auth is a disk token under `~/.gemini/antigravity-cli/`;
  sessions are a **SQLite `conversations*.db`**, so agy uses the generic
  `SqliteSessionSource` rather than a JSONL tailer. The row mapper is
  **provisional** — it will only be registered (and agy marked tailer-capable)
  once verified against a live agy install's DB schema. `agy-ha` isolates each
  session under `HOME=~/.claude-ha/agy-sessions/<id>`, whose DB is at
  `<that-home>/.gemini/antigravity-cli/*.db`; globbing those isolated homes is a
  watcher extension. `po doctor` reports agy honestly as hooks-capable + a
  SQLite store, but not a tailer source until the mapper lands.

- **hermes** is hook-capable via a plugin dir (Orca ships a hermes plugin), but
  no session-file store was located, so it has no tailer path.

- **Adding or updating a CLI = one file.** Create `pixel_office/adapters/<cli>.py`
  defining an `ADAPTER = Adapter(...)` — its `kinds` (kind→activity table),
  `emitted_kinds` (what its parser produces), session spec (`session_kind` +
  `session_glob`/`session_sqlite`), `parse_line` (JSONL) or `sqlite_mapper`
  (SQLite, only once verified against a live DB), hooks, home/binary — then list
  it in `adapters/registry.py`. `doctor`, `normalize`, the tailer, the SQLite
  source, and the conformance test all read from the registry, so nothing else
  changes and drift fails CI automatically.
