"""`po` — Pixel Office command-line entry."""
from __future__ import annotations

import argparse
import glob as _glob
import json
import os
import sys
from pathlib import Path

from . import __version__, doctor


def _cmd_doctor(args) -> int:
    report = doctor.run()
    if args.json:
        print(json.dumps(report, indent=2))
    else:
        print(doctor.format_report(report))
    # non-zero only if the loopback receiver could never bind (a hard blocker)
    return 0 if report["loopback_port"] else 1


def _newest_claude_transcript() -> Path | None:
    from .adapters import registry
    pattern = doctor.session_pattern(registry.get("claude"))
    matches = _glob.glob(pattern) if pattern else []
    if not matches:
        return None
    return Path(max(matches, key=os.path.getmtime))


def _cmd_up(args) -> int:
    try:
        import uvicorn
        from .server import create_app
    except ImportError:
        print('po up needs the web extra: pip install "pixel-office[web]"', file=sys.stderr)
        return 1
    import uuid

    from . import hooks as po_hooks
    hook_token = uuid.uuid4().hex
    if args.file:
        transcript = Path(args.file)
        if not transcript.exists():
            print(f"po up: transcript not found: {transcript}", file=sys.stderr)
            return 1
        app = create_app([transcript], host_id=args.host_id, hook_token=hook_token)
        watching = transcript.name
    else:
        from .adapters import registry
        from .telemetry.watcher import SessionWatcher
        watchers, names = [], []
        for a in registry.all_adapters():
            # jsonl tailer sources with a verified parser that are installed here;
            # missing CLIs degrade gracefully (never block boot)
            if a.session_kind != "jsonl" or a.parse_line is None:
                continue
            if not doctor.which(a):
                continue
            pattern = doctor.session_pattern(a)
            watchers.append(SessionWatcher(pattern, host_id=args.host_id, cli=a.name))
            names.append(a.name)
        if not watchers:
            print("po up: no supported CLIs found — run `po doctor`, or pass --file.",
                  file=sys.stderr)
            return 1
        app = create_app(sources=watchers, host_id=args.host_id, hook_token=hook_token)
        watching = f"all active sessions: {', '.join(names)}"
    po_hooks.write_endpoint_file(args.port, hook_token)  # hooks find us here
    hooks_state = "on" if po_hooks.status().get("installed") else "off — `po hooks install` for live mode"
    print(f"pixel office → http://127.0.0.1:{args.port}   (watching {watching}; hooks {hooks_state})")
    try:
        uvicorn.run(app, host="127.0.0.1", port=args.port, log_level="warning")
    finally:
        # never leave a stale endpoint file pointing at a now-defunct port
        po_hooks.remove_endpoint_file()
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="po", description="Pixel Office — watch your AI company.")
    p.add_argument("-V", "--version", action="version", version=f"pixel-office {__version__}")
    sub = p.add_subparsers(dest="command")
    d = sub.add_parser("doctor", help="show the capability matrix for this machine")
    d.add_argument("--json", action="store_true", help="emit JSON")
    d.set_defaults(func=_cmd_doctor)
    u = sub.add_parser("up", help="watch a CLI session as a live office (loopback only)")
    u.add_argument("--file", help="transcript to watch (default: newest Claude transcript)")
    u.add_argument("--port", type=int, default=7717)
    u.add_argument("--host-id", default="local")
    u.set_defaults(func=_cmd_up)
    h = sub.add_parser("hooks", help="manage the live-mode hook (opt-in upgrade)")
    h.add_argument("action", choices=["install", "uninstall", "status"])
    h.set_defaults(func=_cmd_hooks)
    n = sub.add_parser("new", help="scaffold a new instrumented project (conversational)")
    n.add_argument("--dir", default=".", help="parent directory (default: cwd)")
    n.add_argument("--what", help="one-line description (skips interactive mode)")
    n.add_argument("--name")
    n.add_argument("--goal")
    n.add_argument("--niche")
    n.add_argument("--stack", default="api-service")
    n.add_argument("--benchmarks", help="comma-separated")
    n.add_argument("--roles", help="e.g. '2 writer, 1 editor'")
    n.add_argument("--kr", help="starting Key Results, e.g. "
                   "'publish 10 recipes weekly, reach 1000 signups monthly'")
    n.add_argument("--mode", choices=["Manual", "Copilot", "Autopilot"], default="Copilot",
                   help="how autonomous the AI company runs (default: Copilot)")
    n.add_argument("--product-url", help="live product KPI base URL (e.g. http://127.0.0.1:8000) — "
                   "the growth loop polls it so ideas can be validated against REAL metrics")
    n.add_argument("--yes", action="store_true", help="skip confirmation (non-interactive)")
    n.set_defaults(func=_cmd_new)
    dep = sub.add_parser("deploy", help="detect the env and recommend a promotion path")
    dep.add_argument("--json", action="store_true")
    dep.set_defaults(func=_cmd_deploy)
    r = sub.add_parser("run", help="run a scaffolded project as a live AI company")
    r.add_argument("--dir", default=".", help="project dir with pixel-office.json (default: cwd)")
    r.add_argument("--port", type=int, default=7717)
    r.add_argument("--host-id", default="local")
    # demo (simulated) and live (real work) are mutually exclusive — combining
    # them would fake goal progress while real work spends tokens (dishonest).
    run_mode = r.add_mutually_exclusive_group()
    run_mode.add_argument("--demo", action="store_true",
                          help="simulate employee activity with the deterministic executor (no real work)")
    run_mode.add_argument("--live", action="store_true",
                          help="employees use your real CLIs to do actual work (SPENDS TOKENS)")
    r.set_defaults(func=_cmd_run)
    dm = sub.add_parser("demo", help="watch a sample AI company run itself — zero setup")
    dm.add_argument("--port", type=int, default=7717)
    dm.add_argument("--host-id", default="local")
    dm.set_defaults(func=_cmd_demo)
    return p


def _capability_note() -> str:
    """A compact 'what can I run here' line for onboarding — reuses `po doctor`'s
    probe without dumping the full matrix. Honest: names only what's actually found,
    and never blocks scaffolding (a missing CLI still lets you `po run --demo`)."""
    try:
        avail = [n for n, c in doctor.run().get("clis", {}).items() if c.get("available")]
    except Exception:
        return ""
    if avail:
        return ("detected AI CLIs: " + ", ".join(avail)
                + " — ready for `po up` / `po run --live`.  (`po doctor` for the full matrix)")
    return ("no AI CLIs detected — `po run --demo` still works with zero setup (simulated); "
            "install Claude / Codex / Grok for `po up` and `po run --live`.  (`po doctor` for details)")


def _growth_note(manifest) -> str:
    """Honest onboarding line about outcome validation: with a product URL the growth
    loop can move OKRs (and validate ideas) from REAL metrics; without one, `--live`
    progress and idea outcomes stay unvalidated — we say so rather than implying the
    loop is active."""
    url = getattr(manifest, "product_url", "") or ""
    if not url:
        return ("no product URL set — the growth loop won't have real metrics, so in `--live` "
                "OKRs and idea outcomes stay UNVALIDATED. Add one: `po new --product-url http://…` "
                "(or set PO_PRODUCT_URL), exposing /api/telemetry|funnel|quality|growth.")
    try:                                   # a quick, bounded reachability probe (never blocks)
        from .company import metrics
        got = metrics.fetch_metrics(url, timeout=1.5)
    except Exception:
        got = {}
    if got:                                # only claim validation when KPIs are actually readable
        return (f"growth loop → {url}  ({len(got)} numeric KPI(s) visible). "
                "Idea outcomes will be validated against real metrics.")
    return (f"growth loop → {url}  (no numeric KPIs readable yet — is it running, and does it "
            "expose /api/telemetry|funnel|quality|growth?). Outcomes WON'T validate until it does.")


def _cmd_new(args) -> int:
    from .scaffold import builder
    from .scaffold.init_chat import answers_to_manifest, run_interactive
    from .scaffold.manifest import Manifest

    root = Path(args.dir).resolve()
    if args.what:  # non-interactive: build straight from flags
        manifest = answers_to_manifest({
            "what": args.what, "name": args.name or args.what, "goal": args.goal or "",
            "niche": args.niche or "", "stack": args.stack, "benchmarks": args.benchmarks or "",
            "roles": args.roles or "", "key_results": getattr(args, "kr", None) or "",
            "mode": getattr(args, "mode", None), "product_url": getattr(args, "product_url", None) or "",
        })
        print(manifest.charter())
        if not args.yes:
            print("\nre-run with --yes to create, or use `po new` interactively.")
            return 0
    else:
        manifest = run_interactive(input, lambda p: input(p).strip().lower() in ("y", "yes"), print)
        if manifest is None:
            return 1
    try:
        project = builder.build(manifest, root)
    except (ValueError, OSError) as e:  # OSError covers Permission/IsADirectory/etc.
        print(f"po new: {e}", file=sys.stderr)
        return 1
    rel = project.relative_to(Path.cwd()) if project.is_relative_to(Path.cwd()) else project
    print(f"\ncreated {project}")
    print("next:")
    print(f"  cd {rel}")
    print("  po run --demo    # watch your AI company run itself (simulated, 0 tokens)")
    print("  po run --live    # real: employees use your CLIs (spends tokens)")
    print("  cd backend && uvicorn app:app --reload    # or run the product it builds")
    note = _capability_note()               # onboarding: what can this machine actually run?
    if note:
        print("\n" + note)
    print(_growth_note(manifest))           # onboarding: can idea outcomes be validated?
    return 0


def _cmd_deploy(args) -> int:
    from .control.deploy import detect
    plan = detect()
    if args.json:
        print(json.dumps(plan.__dict__, indent=2))
        return 0
    print("deploy environment:")
    print(f"  localhost : yes")
    print(f"  docker    : {'yes' if plan.docker else 'no'}")
    print(f"  tunnels   : {', '.join(plan.tunnels) or 'none'}")
    print(f"→ recommend : {plan.recommendation}")
    print(f"  phone-reachable: {'yes' if plan.reachable_from_phone else 'no'} — {plan.note}")
    return 0


def _cmd_run(args) -> int:
    # manifest first: if there's nothing to run, "run po new" is the useful message
    # (more actionable than an unrelated missing-dependency note).
    manifest_path = Path(args.dir) / "pixel-office.json"
    if not manifest_path.exists():
        print(f"po run: no pixel-office.json in {args.dir} — run `po new` first.", file=sys.stderr)
        return 1
    try:
        manifest = json.loads(manifest_path.read_text())
    except (OSError, ValueError) as e:
        print(f"po run: can't read {manifest_path}: {e}", file=sys.stderr)
        return 1
    try:
        import uvicorn  # noqa: F401
        from .server import create_app  # noqa: F401
    except ImportError:
        print('po run needs the web extra: pip install "pixel-office[web]"', file=sys.stderr)
        return 1
    from .company.factory import build_company

    company = build_company(manifest, host_id=args.host_id)
    return _serve_company(company, port=args.port, host_id=args.host_id,
                          live=args.live, demo=args.demo)


def _serve_company(company, *, port: int, host_id: str, live: bool = False,
                   demo: bool = False) -> int:
    """Serve one company as a live office (shared by `po run` and `po demo`)."""
    try:
        import uvicorn

        from .server import create_app
    except ImportError:
        print('this needs the web extra: pip install "pixel-office[web]"', file=sys.stderr)
        return 1
    run_mode = "live" if live else "demo" if demo else "dormant"
    app = create_app(sources=[], company=company, host_id=host_id, run_mode=run_mode)
    company.runtime.sink = app.state.hub.ingest
    banner = f"{company.name} · {len(company.team)} employees · mode {company.mode.drive}"
    idea_gen_fn = None
    if live:
        # REAL employees: activate installed CLIs to do actual work. This SPENDS
        # TOKENS. Employees stay dormant until assigned work — no auto-run here.
        from .company.cli_invoke import make_subprocess_invoke
        from .company.executor_cli import CLIExecutor
        _invoke = make_subprocess_invoke()
        company.runtime.executor = CLIExecutor(invoke_fn=_invoke,
                                               memories=company.runtime.memories,
                                               objective=company.okrs.objective)
        try:                                   # live NEEDS a real CLI — say so loudly, don't fail silent
            _avail = [n for n, c in doctor.run().get("clis", {}).items() if c.get("available")]
        except Exception:
            _avail = []
        # idea generation uses an ACTUALLY-available CLI, not a hardcoded one (detection
        # may advertise codex/grok while claude is absent).
        _idea_cli = next((c for c in ("claude", "codex", "grok") if c in _avail), None)

        def idea_gen_fn(objective, family, lens, target):   # noqa: E306 — real creativity in --live
            # a real CLI writes the idea CONTENT (the autonomy loop calls this OUTSIDE
            # the company lock). Returns "" if no compatible CLI or on any error — the
            # loop then SKIPS the proposal in live (never attributes a skeleton to the
            # employee as if their CLI wrote it).
            if not _idea_cli:
                return ""
            prompt = (f"You are a {family} specialist at a company whose goal is: {objective}.\n"
                      f"Propose ONE small, reversible, creative idea to move this metric: {target}.\n"
                      f"Think specifically through the '{lens}' lens. Reply in 1-2 sentences; "
                      f"end with 'Assumption: <your key assumption>'.")
            try:
                return str(_invoke(_idea_cli, prompt) or "")[:400]
            except Exception:
                return ""
        banner += " · LIVE (real CLI agents — spends tokens; dormant until assigned)"
        print("live: employees will use your real CLIs and SPEND TOKENS when assigned work.",
              file=sys.stderr)
        if not _avail:
            print("live: WARNING — no AI CLI detected on PATH. Employees will be Blocked when "
                  "assigned. Install Claude/Codex/Grok (`po doctor`), or use `po run --demo`.",
                  file=sys.stderr)
        if not getattr(company, "product_url", ""):
            print("live: no product URL — OKRs and idea outcomes stay UNVALIDATED (no real "
                  "metrics). Set PO_PRODUCT_URL or `product_url` in pixel-office.json.",
                  file=sys.stderr)
    elif demo:
        # DEMO: the deterministic executor SIMULATES work (no real LLM, 0 tokens)
        # so you can see the office move. This is explicitly not real work.
        from .company.runtime import Task
        company.simulated = True   # honest: the dashboard labels this progress as simulated
        for emp in company.team.all():
            company.runtime.assign(Task(f"[demo] orient on: {company.okrs.objective}", dri=emp.id))
        banner += " · DEMO (simulated activity, no real work)"
    else:
        banner += " · employees dormant until given real work (--demo to simulate)"
    # autonomy: the company runs itself toward the goal on a background tick (only in
    # demo/live). In demo the cadences are lively so meetings/ideas are visible fast.
    stop = None
    thread = None
    if demo or live:
        import threading
        import time as _time

        from .company.autonomy import AutonomyLoop, planner_for
        loop = AutonomyLoop(company, planner_fn=planner_for(company), max_dispatch=2,
                            review_every_s=(30 if demo else 3600),
                            radar_every_s=(60 if demo else 6 * 3600),
                            hr_every_s=(90 if demo else 12 * 3600),
                            meeting_every_s=(40 if demo else 4 * 3600),
                            initiative_every_s=(25 if demo else 6 * 3600),
                            metrics_every_s=(20 if demo else 300),
                            idea_gen_fn=idea_gen_fn)
        stop = threading.Event()
        interval = 6.0

        def _autonomy():
            while not stop.wait(interval):
                try:
                    loop.tick(_time.monotonic())
                    if demo:                     # simulate KR metrics landing so the
                        with company._lock:      # goal visibly grows (labelled 'simulated')
                            t = loop._ticks       # DETERMINISTIC variation (no RNG) so growth
                            for idx, kr in enumerate(company.okrs.key_results):
                                if kr.current < kr.target:
                                    # is bumpy, not constant — some ideas land above the
                                    # baseline trend (assoc.), some below (failed): honest spread.
                                    mult = 0.4 + 1.2 * ((t * 7 + idx * 5) % 5) / 4.0
                                    step = max(1.0, kr.target * 0.05 * mult)
                                    company.okrs.update(kr.id, min(kr.target, kr.current + step))
                except Exception:
                    pass   # the loop must never crash the server
        thread = threading.Thread(target=_autonomy, name="po-autonomy", daemon=True)
        thread.start()
        banner += " · autonomy running"
    print(f"pixel office → http://127.0.0.1:{port}   ({banner})")
    try:
        uvicorn.run(app, host="127.0.0.1", port=port, log_level="warning")
    finally:
        if stop is not None:
            stop.set()
        if thread is not None:
            thread.join(timeout=interval + 5)  # let an in-flight tick finish cleanly
    return 0


# a canned sample company so `po demo` shows a living AI company with zero setup
SAMPLE_MANIFEST = {
    "name": "Acme AI", "what": "an AI-run SaaS", "goal": "reach 1000 weekly signups",
    "stack": "chat-product", "mode": "Autopilot",
    "roles": [{"title": "Project Owner"}, {"title": "Architecture Engineer"},
              {"title": "Backend Engineer"}, {"title": "Frontend Engineer"},
              {"title": "Growth Marketer"}, {"title": "Content Writer"}, {"title": "QA Engineer"}],
    "key_results": [{"text": "ship 5 features weekly", "target": 5, "cadence": "weekly"},
                    {"text": "reach 1000 signups monthly", "target": 1000, "cadence": "monthly",
                     "metric": "signups"},
                    {"text": "publish 10 posts weekly", "target": 10, "cadence": "weekly"}],
}


def _cmd_demo(args) -> int:
    try:
        import uvicorn  # noqa: F401
    except ImportError:
        print('po demo needs the web extra: pip install "pixel-office[web]"', file=sys.stderr)
        return 1
    from .company.factory import build_company
    company = build_company(SAMPLE_MANIFEST, host_id=args.host_id)
    print("po demo: a sample AI company running itself — simulated, zero tokens, no setup.")
    return _serve_company(company, port=args.port, host_id=args.host_id, demo=True)


def _cmd_hooks(args) -> int:
    from . import hooks as po_hooks
    try:
        if args.action == "install":
            print(po_hooks.install())
        elif args.action == "uninstall":
            print(po_hooks.uninstall())
        else:
            print(json.dumps(po_hooks.status(), indent=2))
        return 0
    except RuntimeError as e:
        print(f"po hooks: {e}", file=sys.stderr)
        return 1


def main(argv=None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if not getattr(args, "func", None):
        parser.print_help()
        return 0
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
