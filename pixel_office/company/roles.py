"""Built-in role library — the canonical jobs a software company hires for
(docs/COMPANY-LAYER.md).

Each role ships a persona (voice/rules), a default model tier, the skills it holds,
and the workflows it can drive — so a scaffolded company arrives knowing HOW to run
a service, not just a list of title strings. `match_title` resolves a user's
free-text role to a library role, returning None on an ambiguous/unknown title
(the caller then keeps a plain employee — never a confident-wrong mapping).
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, Optional, Tuple

from . import skills as _skills

TIERS = ("cheap", "standard", "deep")


@dataclass(frozen=True)
class RoleSpec:
    id: str
    title: str
    family: str                       # one of skills.FAMILIES
    tier: str = "cheap"
    persona: str = ""                 # cached role rules / voice preamble
    skills: Tuple[str, ...] = ()      # skill ids from skills.SKILLS
    workflows: Tuple[str, ...] = ()   # workflow ids from workflows.WORKFLOWS
    creative: bool = False


def _r(id, title, family, tier, persona, skills, workflows, creative=False) -> RoleSpec:
    return RoleSpec(id=id, title=title, family=family, tier=tier, persona=persona,
                    skills=tuple(skills), workflows=tuple(workflows), creative=creative)


ROLES: Dict[str, RoleSpec] = {r.id: r for r in (
    _r("project-owner", "Project Owner", "engineering", "standard",
       "You are the single-threaded owner. Turn the objective into crisp specs and "
       "the one decision that unblocks the team; prefer the least-work path that ships.",
       ("api-design",), ("ship-feature",)),
    _r("architect", "Architecture Engineer", "engineering", "deep",
       "You are a high-performance architecture engineer. Lead with trade-offs and "
       "measurable constraints (latency, scale, cost); pick the simplest design that "
       "meets them and write it down.",
       ("system-design", "api-design", "architecture-review", "tradeoff-analysis", "perf-optimization"),
       ("architecture-review", "ship-feature")),
    _r("backend", "Backend Engineer", "engineering", "standard",
       "You build reliable services. Small, tested changes; clear contracts; never "
       "break the instrumentation surface.",
       ("backend-impl", "api-design", "database", "testing"), ("ship-feature",)),
    _r("frontend", "Frontend Engineer", "engineering", "standard",
       "You build the client. Accessible, fast, honest UI wired to real telemetry.",
       ("frontend-impl", "ui-design", "testing"), ("ship-feature",)),
    _r("qa", "QA Engineer", "engineering", "cheap",
       "You are the safety net. Reproduce, add a failing test first, verify the fix, "
       "guard against regressions.",
       ("testing", "code-review"), ("ship-feature",)),
    _r("devops", "DevOps / SRE", "engineering", "standard",
       "You own reliable delivery. Reproducible builds, least-public deploys, fast "
       "rollback; fail closed on anything risky.",
       ("devops-ci", "security", "perf-optimization"), ("ship-feature", "incident-response")),
    _r("pm", "Product Manager", "engineering", "standard",
       "You keep the roadmap honest. Sequence by value and evidence; cut scope before "
       "cutting quality.",
       ("api-design",), ("ship-feature",)),
    _r("designer", "Product Designer", "design", "standard",
       "You design the experience. Clear flows, consistent visuals, prototypes over "
       "opinions.",
       ("ui-design", "ux-research", "visual-design"), ("ship-feature",), creative=True),
    _r("writer", "Content Writer", "content", "cheap",
       "You write for the reader. Concrete, well-edited, SEO-aware content — no filler.",
       ("copywriting", "content-editing", "seo", "video-script"), ("content-pipeline",), creative=True),
    _r("growth", "Growth Marketer", "growth", "standard",
       "You grow the north-star metric with cheap, measurable experiments — hypothesis, "
       "instrument, measure, decide.",
       ("growth-experiment", "acquisition", "retention-analysis"), ("growth-experiment",), creative=True),
    _r("data", "Data Analyst", "data", "standard",
       "You turn data into decisions. Query, quantify, and report what actually moved "
       "the metric — no vanity numbers.",
       ("data-analysis", "sql", "ml-modeling", "dashboarding"), ("growth-experiment",)),
)}


# per-stack default team (each <= MAX_ROLES = 12) — seeded when the user names no roles
DEFAULT_TEAMS: Dict[str, Tuple[str, ...]] = {
    "api-service":   ("project-owner", "architect", "backend", "qa", "devops"),
    "data-pipeline": ("project-owner", "architect", "data", "backend", "devops"),
    "chat-product":  ("project-owner", "architect", "backend", "frontend", "designer", "writer", "growth"),
}


def get(role_id: str) -> Optional[RoleSpec]:
    return ROLES.get(role_id)


def is_creative(employee) -> bool:
    """Whether an employee's library role is a creative one — the single source of
    truth (don't duplicate the flag onto Employee)."""
    spec = ROLES.get(getattr(employee, "role", "") or "")
    return bool(spec and spec.creative)


def family_of(role_id: str) -> str:
    spec = ROLES.get(role_id or "")
    return spec.family if spec else ""


def default_team_for(stack: str) -> Tuple[str, ...]:
    return DEFAULT_TEAMS.get(str(stack or "").strip().lower(), ())


def _role_signals(spec: RoleSpec):
    # a role's OWN title/id words are the strong signal; its skill keywords are a
    # weaker one (shared skills like "testing" leak the word "qa" into many roles,
    # so they must not outweigh the title).
    primary = _skills.words(spec.title) | _skills.words(spec.id.replace("-", " "))
    return primary, _skills.keywords_for(spec.skills)


def match_title(title: str) -> Optional[RoleSpec]:
    """Resolve a free-text role title to a library role, weighting the role's own
    title/id words above its (often shared) skill keywords. None when nothing
    matches or the top two tie (ambiguous → caller keeps the plain title, never a
    confident-wrong mapping)."""
    want = _skills.words(title)
    if not want:
        return None

    def score(r: RoleSpec) -> int:
        primary, secondary = _role_signals(r)
        return 2 * len(want & primary) + len(want & secondary)

    scored = sorted(((score(r), r.id) for r in ROLES.values()),
                    key=lambda t: (t[0], t[1]), reverse=True)
    # require a real signal (a title/id word = 2, a lone shared skill keyword = 1):
    # a single stray skill-keyword hit is too weak to confidently assign a role.
    if not scored or scored[0][0] < 2:
        return None
    if len(scored) > 1 and scored[1][0] == scored[0][0]:
        return None
    return ROLES[scored[0][1]]
