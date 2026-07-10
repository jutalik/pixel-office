# Pixel Office

**Spin up an AI company you can *watch*.**

Pixel Office turns your AI coding CLIs into a live, game-like office: every running
agent, subagent, LLM call, and workflow shows up as an **avatar** that moves between
rooms and shows what it's doing — driven entirely by telemetry from the tools you
already use (Claude Code, Codex, Grok, Gemini, and more).

> **Status: Phase 0 shipped.** The telemetry contract is frozen as code
> (`pixel_office/telemetry/`), the deterministic reducer passes golden replay tests, and
> `po doctor` prints this machine's capability matrix. Phase 1a (first live avatar) is next —
> see [`ROADMAP.md`](ROADMAP.md).

## Quickstart

```bash
pip install -e ".[dev]"
po doctor        # which CLIs are installed, hook-capable, and tailable
pytest -q        # golden replay + contract invariants
```

## The vision

- **Conversational init** — a non-developer answers a few questions (what service,
  goal, benchmarks, niche) and Pixel Office scaffolds a real project for them.
- **Instrumented from birth** — the scaffold ships telemetry-complete, so the office
  dashboard works no matter what the agents build on top of it.
- **Watch it work** — a pixel office where avatars act out *real* agent activity.
  Honest by design: an avatar only moves when something real happens.
- **Local-first** — runs on your machine. Bring your own CLIs; sign in with whatever
  you already have (subscription **or** API key). Pixel Office stores no tokens.

## Design principles

- **Delegate auth** to each CLI's native login; never store or refresh tokens.
- Telemetry fails **open** (never blocks your tools); privileged actions fail **closed**.
- Avatars are **honest** — no faked or overstated activity.
- **Light enough for a weak laptop.** The game layer is optional and can be turned off
  (`PO_OVERLAY=off`) to leave a pure headless core.

## Documentation

| Doc | What it covers |
|---|---|
| [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) | The core/overlay split and the telemetry pipeline |
| [`docs/DECISIONS.md`](docs/DECISIONS.md) | Locked decisions and their rationale |
| [`docs/TELEMETRY-CONTRACT.md`](docs/TELEMETRY-CONTRACT.md) | The event/identity contract (frozen before any dashboard code) |
| [`ROADMAP.md`](ROADMAP.md) | Dependency-ordered build plan |

The design was pressure-tested through a multi-model deliberation (Claude, Codex, Grok);
see `docs/DECISIONS.md` for what each contributed and where they disagreed.

## License

MIT — see [`LICENSE`](LICENSE).
