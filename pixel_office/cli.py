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
    return p


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
            "mode": getattr(args, "mode", None),
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
    print(f"\ncreated {project}")
    print(f"  cd {project.relative_to(Path.cwd()) if project.is_relative_to(Path.cwd()) else project}"
          f"/backend && uvicorn app:app --reload")
    print("  then `po up` to watch your team build it")
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
    try:
        import uvicorn
        from .server import create_app
    except ImportError:
        print('po run needs the web extra: pip install "pixel-office[web]"', file=sys.stderr)
        return 1
    from .company.factory import build_company
    from .company.runtime import Task

    manifest_path = Path(args.dir) / "pixel-office.json"
    if not manifest_path.exists():
        print(f"po run: no pixel-office.json in {args.dir} — run `po new` first.", file=sys.stderr)
        return 1
    try:
        manifest = json.loads(manifest_path.read_text())
    except (OSError, ValueError) as e:
        print(f"po run: can't read {manifest_path}: {e}", file=sys.stderr)
        return 1
    company = build_company(manifest, host_id=args.host_id)
    run_mode = "live" if args.live else "demo" if args.demo else "dormant"
    app = create_app(sources=[], company=company, host_id=args.host_id, run_mode=run_mode)
    company.runtime.sink = app.state.hub.ingest
    banner = f"{company.name} · {len(company.team)} employees · mode {company.mode.drive}"
    if args.live:
        # REAL employees: activate installed CLIs to do actual work. This SPENDS
        # TOKENS. Employees stay dormant until assigned work — no auto-run here.
        from .company.cli_invoke import make_subprocess_invoke
        from .company.executor_cli import CLIExecutor
        company.runtime.executor = CLIExecutor(invoke_fn=make_subprocess_invoke(),
                                               memories=company.runtime.memories)
        banner += " · LIVE (real CLI agents — spends tokens; dormant until assigned)"
        print("po run --live: employees will use your real CLIs and SPEND TOKENS when assigned work.",
              file=sys.stderr)
    elif args.demo:
        # DEMO: the deterministic executor SIMULATES work (no real LLM, 0 tokens)
        # so you can see the office move. This is explicitly not real work.
        from .company.runtime import Task
        company.simulated = True   # honest: the dashboard labels this progress as simulated
        for emp in company.team.all():
            company.runtime.assign(Task(f"[demo] orient on: {company.okrs.objective}", dri=emp.id))
        banner += " · DEMO (simulated activity, no real work)"
    else:
        banner += " · employees dormant until given real work (--demo to simulate)"
    # autonomy: the company runs itself toward the goal on a background tick
    # (only in demo/live — dormant default stays idle). Uses the hub lock for
    # thread-safe ingest.
    stop = None
    thread = None
    if args.demo or args.live:
        import threading
        import time as _time

        from .company.autonomy import AutonomyLoop, planner_for
        loop = AutonomyLoop(company, planner_fn=planner_for(company), max_dispatch=2,
                            review_every_s=30, radar_every_s=60, hr_every_s=90)
        stop = threading.Event()
        interval = 6.0

        demo = args.demo   # DEMO simulates KR metrics landing so the goal visibly
                           # grows; --live never fabricates progress (real metrics only)

        def _autonomy():
            while not stop.wait(interval):
                try:
                    loop.tick(_time.monotonic())
                    if demo:
                        with company._lock:
                            for kr in company.okrs.key_results:
                                if kr.current < kr.target:  # nudge toward target (simulated)
                                    step = max(1.0, kr.target * 0.05)
                                    company.okrs.update(kr.id, min(kr.target, kr.current + step))
                except Exception:
                    pass   # the loop must never crash the server
        thread = threading.Thread(target=_autonomy, name="po-autonomy", daemon=True)
        thread.start()
        banner += " · autonomy running"
    print(f"pixel office → http://127.0.0.1:{args.port}   ({banner})")
    try:
        uvicorn.run(app, host="127.0.0.1", port=args.port, log_level="warning")
    finally:
        if stop is not None:
            stop.set()
        if thread is not None:
            thread.join(timeout=interval + 5)  # let an in-flight tick finish cleanly
    return 0


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
