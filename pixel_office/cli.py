"""`po` — Pixel Office command-line entry."""
from __future__ import annotations

import argparse
import json
import sys

from . import __version__, doctor


def _cmd_doctor(args) -> int:
    report = doctor.run()
    if args.json:
        print(json.dumps(report, indent=2))
    else:
        print(doctor.format_report(report))
    # non-zero only if the loopback receiver could never bind (a hard blocker)
    return 0 if report["loopback_port"] else 1


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="po", description="Pixel Office — watch your AI company.")
    p.add_argument("-V", "--version", action="version", version=f"pixel-office {__version__}")
    sub = p.add_subparsers(dest="command")
    d = sub.add_parser("doctor", help="show the capability matrix for this machine")
    d.add_argument("--json", action="store_true", help="emit JSON")
    d.set_defaults(func=_cmd_doctor)
    return p


def main(argv=None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if not getattr(args, "func", None):
        parser.print_help()
        return 0
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
