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
    spec = doctor._CLIS["claude"]
    home = doctor._resolve_home(spec)
    matches = _glob.glob(str(home / spec["session_glob"]))
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
        from .telemetry.normalize import known_clis
        from .telemetry.watcher import SessionWatcher
        watchers, names = [], []
        for cli_name in known_clis():  # every CLI with a normalize table + parser
            spec = doctor._CLIS.get(cli_name)
            if not spec or not spec["session_glob"]:
                continue
            if not doctor._which(cli_name, spec["extra_bin_dirs"]):
                continue  # not installed — degrade gracefully, never fail boot
            pattern = str(doctor._resolve_home(spec) / spec["session_glob"])
            watchers.append(SessionWatcher(pattern, host_id=args.host_id, cli=cli_name))
            names.append(cli_name)
        if not watchers:
            print("po up: no supported CLIs found — run `po doctor`, or pass --file.",
                  file=sys.stderr)
            return 1
        app = create_app(sources=watchers, host_id=args.host_id, hook_token=hook_token)
        watching = f"all active sessions: {', '.join(names)}"
    po_hooks.write_endpoint_file(args.port, hook_token)  # hooks find us here
    hooks_state = "on" if po_hooks.status().get("installed") else "off — `po hooks install` for live mode"
    print(f"pixel office → http://127.0.0.1:{args.port}   (watching {watching}; hooks {hooks_state})")
    uvicorn.run(app, host="127.0.0.1", port=args.port, log_level="warning")
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
    n.add_argument("--yes", action="store_true", help="skip confirmation (non-interactive)")
    n.set_defaults(func=_cmd_new)
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
            "roles": args.roles or "",
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
    except (FileExistsError, ValueError) as e:
        print(f"po new: {e}", file=sys.stderr)
        return 1
    print(f"\ncreated {project}")
    print(f"  cd {project.relative_to(Path.cwd()) if project.is_relative_to(Path.cwd()) else project}"
          f"/backend && uvicorn app:app --reload")
    print("  then `po up` to watch your team build it")
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
