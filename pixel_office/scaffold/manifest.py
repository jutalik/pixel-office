"""The extended init manifest — what conversational/menu init collects.

Shape (locked in DECISIONS.md, extended from the pixel-office supervisor manifest):
    what       — the service to build (title + one-line pitch)
    goal       — north-star metric the company optimizes
    benchmarks — reference/competitor projects (feed the agents' self-research)
    niche      — target audience / segment
    stack      — one of the instrumentation-complete templates
    roles      — the initial team (title + count), recorded in the manifest and
                 charter for the team's own planning. NOTE: roles are NOT rendered
                 as avatars — avatars come only from real CLI session telemetry.

The manifest is `trusted=False` by default (came from a model or an untrusted
user): capability-shaped fields are sanitized, values are bounded, and NOTHING
here is ever executed — it only describes a project to scaffold.
"""
from __future__ import annotations

import math
import re
from dataclasses import dataclass, field
from typing import List

from ..company.mode import OperatingMode
from .templates import TEMPLATES

_NAME_RE = re.compile(r"[^a-z0-9-]+")
MAX_STR = 200
MAX_ROLES = 12
MAX_BENCHMARKS = 10
MAX_KRS = 8
CADENCES = ("weekly", "monthly")


def slugify(name: str) -> str:
    slug = _NAME_RE.sub("-", str(name).strip().lower()).strip("-")
    return (slug or "project")[:40]


def _clean_str(v, limit: int = MAX_STR) -> str:
    return str(v or "").strip().replace("\n", " ")[:limit]


def _clean_krs(raw) -> List["KeyResultSpec"]:
    """Normalize manifest key_results (list of dicts) into bounded, valid specs.
    A KR with a non-finite / non-positive target or empty text is dropped, never
    fabricated into something measurable it isn't."""
    raw = raw if isinstance(raw, (list, tuple)) else []
    out: List[KeyResultSpec] = []
    for k in raw[:MAX_KRS]:
        if not isinstance(k, dict):
            continue
        text = _clean_str(k.get("text"), 120)
        if not text:
            continue
        try:
            target = float(k.get("target", 1.0))
        except (TypeError, ValueError):
            target = 1.0
        if not math.isfinite(target) or target <= 0:
            target = 1.0
        cadence = str(k.get("cadence") or "weekly").strip().lower()
        if cadence not in CADENCES:
            cadence = "weekly"
        out.append(KeyResultSpec(text=text, target=target, cadence=cadence,
                                 metric=_clean_str(k.get("metric"), 40)))
    return out


@dataclass(frozen=True)
class Role:
    title: str
    count: int = 1


@dataclass(frozen=True)
class KeyResultSpec:
    """A user-provided starting Key Result (measurable). Not fabricated — the
    company advances these; the objective stays at 0% until they progress."""
    text: str
    target: float = 1.0
    cadence: str = "weekly"     # weekly | monthly
    metric: str = ""            # optional KPI keyword the growth loop matches


@dataclass(frozen=True)
class Manifest:
    name: str
    what: str
    goal: str = ""
    niche: str = ""
    stack: str = "api-service"
    benchmarks: List[str] = field(default_factory=list)
    roles: List[Role] = field(default_factory=list)
    key_results: List[KeyResultSpec] = field(default_factory=list)
    mode: OperatingMode = field(default_factory=OperatingMode)
    product_url: str = ""    # live KPI surface the growth loop polls (validates idea outcomes)

    @property
    def slug(self) -> str:
        return slugify(self.name)

    @staticmethod
    def from_dict(d: dict) -> "Manifest":
        if not isinstance(d, dict):
            raise ValueError("manifest must be an object")
        what = _clean_str(d.get("what"))
        if not what:
            raise ValueError("manifest.what (what to build) is required")
        stack = str(d.get("stack") or "api-service")
        if stack not in TEMPLATES:
            raise ValueError(f"unknown stack {stack!r}; choose one of {sorted(TEMPLATES)}")
        raw_roles = d.get("roles")
        raw_roles = raw_roles if isinstance(raw_roles, (list, tuple)) else []
        roles = []
        for r in raw_roles[:MAX_ROLES]:
            if isinstance(r, dict):
                title = _clean_str(r.get("title"), 60)
                try:
                    count = max(1, min(20, int(r.get("count", 1))))
                except (TypeError, ValueError):
                    count = 1
            else:
                title, count = _clean_str(r, 60), 1
            if title:
                roles.append(Role(title=title, count=count))
        raw_bench = d.get("benchmarks")
        raw_bench = raw_bench if isinstance(raw_bench, (list, tuple)) else []
        benchmarks = [_clean_str(b, 120) for b in raw_bench[:MAX_BENCHMARKS]]
        benchmarks = [b for b in benchmarks if b]
        return Manifest(
            name=_clean_str(d.get("name") or what, 60),
            what=what,
            goal=_clean_str(d.get("goal")),
            niche=_clean_str(d.get("niche")),
            stack=stack,
            benchmarks=benchmarks,
            roles=roles or [Role("Founder", 1)],
            key_results=_clean_krs(d.get("key_results")),
            mode=OperatingMode.from_dict(d.get("mode")) if d.get("mode") else OperatingMode(),
            product_url=_clean_str(d.get("product_url"), 300),
        )

    def charter(self) -> str:
        """Plain-language confirmation shown before anything is created."""
        team = ", ".join(f"{r.count}× {r.title}" for r in self.roles)
        lines = [
            f"Company : {self.name}  (dir: {self.slug}/)",
            f"Building : {self.what}",
            f"Goal     : {self.goal or '(none set — you can add a north-star metric later)'}",
            f"Niche    : {self.niche or '(broad)'}",
            f"Stack    : {self.stack}  ({TEMPLATES[self.stack].summary})",
            f"Team     : {team}",
            f"Mode     : {self.mode.drive}  (CEO sees: {self.mode.ceo_updates.lower()})",
        ]
        if self.key_results:
            krs = "; ".join(f"{k.text} → {k.target:g} ({k.cadence})" for k in self.key_results)
            lines.append(f"Key Results: {krs}")
        if self.benchmarks:
            lines.append(f"Benchmarks: {', '.join(self.benchmarks)}")
        return "\n".join(lines)
