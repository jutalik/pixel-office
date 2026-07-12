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

import re
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
    ("key_results", "First measurable targets? (e.g. 'publish 10 recipes weekly, reach 1000 signups monthly' "
                    "— blank to set later)", False),
    ("mode", "How autonomous should the company run? Manual / Copilot / Autopilot (blank=Copilot)", False),
]

_NUM_RE = re.compile(r"\d+(?:\.\d+)?")

# Action verbs / fillers that describe HOW a KR is pursued, not WHAT it measures.
# The KPI keyword is the noun left after these (and the number) are removed, so a
# natural-language KR can auto-update from the product's metric surface.
_KR_STOPWORDS = frozenset({
    "reach", "ship", "publish", "get", "grow", "hit", "achieve", "launch", "add",
    "drive", "increase", "raise", "reduce", "cut", "keep", "maintain", "deliver",
    "to", "a", "an", "the", "of", "per", "our", "new", "active", "total", "at",
    "least", "under", "over", "and", "or", "by", "below", "above", "than",
    "from", "with", "into", "up", "down",
})


def _kr_metric(text: str) -> str:
    """Best-effort KPI keyword from a KR phrase: the last salient noun once the
    number and action words are stripped (e.g. 'reach 1000 weekly signups' →
    'signups'). Empty when nothing measurable is named — apply_metrics then simply
    won't auto-match it, so no false KPI updates are invented."""
    words = [w.lower() for w in re.findall(r"[A-Za-z]+", text)]
    nouns = [w for w in words if w not in _KR_STOPWORDS]
    return nouns[-1] if nouns else ""


def _parse_krs(text: str) -> List[dict]:
    """Turn plain phrases into KR dicts. Each comma-separated phrase keeps its
    words as the KR text; the first number in it is the target; a 'weekly'/
    'monthly' word (default weekly) sets the cadence; a KPI keyword is derived so
    the growth loop can match it to a product metric. No number → target 1 (a
    binary milestone), so nothing measurable is invented."""
    out = []
    # drop thousands separators (a comma between digits) so '1,000' stays one KR
    text = re.sub(r"(?<=\d),(?=\d)", "", str(text or ""))
    for part in text.split(","):
        part = part.strip()
        if not part:
            continue
        cadence = "weekly"
        for c in ("monthly", "weekly"):
            if re.search(rf"\b{c}\b", part, flags=re.I):
                cadence = c
                part = re.sub(rf"\b{c}\b", "", part, flags=re.I)
                break
        part = " ".join(part.split())   # collapse the gap the cadence word left
        m = _NUM_RE.search(part)
        target = float(m.group()) if m else 1.0
        out.append({"text": part or "goal", "target": target, "cadence": cadence,
                    "metric": _kr_metric(part)})
    return out


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
        "key_results": _parse_krs(answers.get("key_results", "")),
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
