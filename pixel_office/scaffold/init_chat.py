"""Conversational init — turn a short Q&A into a manifest, no LLM required.

Non-developers get either a guided prompt sequence (interactive) or answer a
menu; the SAME questions build the manifest. An LLM can pre-fill the draft, but
the flow never depends on one being available — the deterministic path always
works offline, which matters for the local-first, zero-setup promise.

The final step ALWAYS shows the plain-language charter and requires confirmation
before anything is written (the Phase-0 fix for "a broken seed agents can't
repair").
"""
from __future__ import annotations

from typing import Callable, Dict, List, Optional

from .manifest import Manifest
from .templates import TEMPLATES

# (key, prompt, required) — the questions init asks, in order.
QUESTIONS = [
    ("what", "What do you want to build? (one line)", True),
    ("name", "Company/product name?", False),
    ("goal", "What's the goal — the one metric that means you're winning?", False),
    ("niche", "Who is it for? (audience / niche)", False),
    ("benchmarks", "Any projects to benchmark against? (comma-separated)", False),
    ("stack", f"Stack? one of: {', '.join(TEMPLATES)}", False),
    ("roles", "Starting team? (e.g. '2 writer, 1 editor' — blank for a solo founder)", False),
    ("mode", "How autonomous should the company run? Manual / Copilot / Autopilot (blank=Copilot)", False),
]


def _parse_roles(text: str) -> List[dict]:
    roles = []
    for part in str(text or "").split(","):
        part = part.strip()
        if not part:
            continue
        toks = part.split(None, 1)
        if toks and toks[0].isdigit():
            roles.append({"count": int(toks[0]), "title": toks[1] if len(toks) > 1 else "member"})
        else:
            roles.append({"count": 1, "title": part})
    return roles


def answers_to_manifest(answers: Dict[str, str]) -> Manifest:
    d = {
        "what": answers.get("what", ""),
        "name": answers.get("name") or answers.get("what", ""),
        "goal": answers.get("goal", ""),
        "niche": answers.get("niche", ""),
        "stack": (answers.get("stack") or "api-service").strip() or "api-service",
        "benchmarks": [b.strip() for b in str(answers.get("benchmarks", "")).split(",") if b.strip()],
        "roles": _parse_roles(answers.get("roles", "")),
        "mode": (answers.get("mode") or "").strip() or "Copilot",
    }
    return Manifest.from_dict(d)


def run_interactive(ask: Callable[[str], str], confirm: Callable[[str], bool],
                    say: Callable[[str], None]) -> Optional[Manifest]:
    """Drive the Q&A with injectable io (testable; the CLI passes real input)."""
    answers: Dict[str, str] = {}
    for key, prompt, required in QUESTIONS:
        while True:
            ans = ask(prompt).strip()
            if ans or not required:
                answers[key] = ans
                break
            say("  (required)")
    try:
        manifest = answers_to_manifest(answers)
    except ValueError as e:
        say(f"couldn't build a project from that: {e}")
        return None
    say("\n--- company charter ---\n" + manifest.charter() + "\n-----------------------")
    if not confirm("Create this project? [y/N] "):
        say("cancelled — nothing written.")
        return None
    return manifest
