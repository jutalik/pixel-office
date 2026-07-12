"""Skill catalog — the atomic unit of what an employee is good at (docs/COMPANY-LAYER.md).

A skill is a named competency with routing keywords and a default model tier. An
employee's *proficiency* at a skill is NEVER a declared number — it is derived from
evidence (learning.EmployeeMemory.competency) and reports "insufficient evidence"
(None) below the sample floor, exactly like every other competency in this codebase.

Skills feed two things: routing (keyword overlap → the right owner) and honest
proficiency display. They never fabricate ability.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Dict, Iterable, List, Optional, Tuple

# The five role families (kept in lockstep with routing.ROLE_FAMILIES keys).
FAMILIES = ("engineering", "content", "growth", "design", "data")
TIERS = ("cheap", "standard", "deep")

_WORD = re.compile(r"[a-z0-9]+")


@dataclass(frozen=True)
class Skill:
    id: str
    title: str
    family: str                      # one of FAMILIES
    keywords: Tuple[str, ...] = ()   # routing signal words (a task/KR matching these routes here)
    tier_hint: str = "cheap"         # cheap | standard | deep — routine → hard/creative


def _mk(id, title, family, keywords, tier="cheap") -> Skill:
    return Skill(id=id, title=title, family=family, keywords=tuple(keywords), tier_hint=tier)


# ── the catalog ──────────────────────────────────────────────────────────────
SKILLS: Dict[str, Skill] = {s.id: s for s in (
    # engineering
    _mk("system-design", "System design", "engineering",
        ("architecture", "system", "design", "scale", "scalability", "distributed"), "deep"),
    _mk("architecture-review", "Architecture review", "engineering",
        ("architecture", "review", "tradeoff", "adr", "decision"), "deep"),
    _mk("tradeoff-analysis", "Trade-off analysis", "engineering",
        ("tradeoff", "tradeoffs", "benchmark", "compare", "evaluate"), "deep"),
    _mk("api-design", "API design", "engineering",
        ("api", "endpoint", "endpoints", "contract", "schema", "rest"), "standard"),
    _mk("backend-impl", "Backend implementation", "engineering",
        ("backend", "server", "service", "feature", "endpoint", "api", "code"), "standard"),
    _mk("frontend-impl", "Frontend implementation", "engineering",
        ("frontend", "ui", "client", "page", "component", "web"), "standard"),
    _mk("database", "Database & storage", "engineering",
        ("database", "db", "sql", "schema", "migration", "query", "index"), "standard"),
    _mk("perf-optimization", "Performance optimization", "engineering",
        ("performance", "perf", "latency", "throughput", "optimize", "uptime"), "deep"),
    _mk("testing", "Testing & QA", "engineering",
        ("test", "tests", "qa", "coverage", "regression", "verify"), "cheap"),
    _mk("code-review", "Code review", "engineering",
        ("review", "code", "pr", "quality", "lint"), "standard"),
    _mk("security", "Security", "engineering",
        ("security", "auth", "vulnerability", "secret", "hardening", "audit"), "deep"),
    _mk("devops-ci", "DevOps / CI-CD", "engineering",
        ("deploy", "ci", "cd", "infra", "infrastructure", "docker", "pipeline", "release"), "standard"),
    # content
    _mk("copywriting", "Copywriting", "content",
        ("copy", "write", "writing", "article", "post", "blog", "recipe", "story", "content"), "cheap"),
    _mk("content-editing", "Editing", "content",
        ("edit", "editor", "editorial", "proofread", "polish"), "cheap"),
    _mk("seo", "SEO", "content",
        ("seo", "keyword", "keywords", "ranking", "search"), "cheap"),
    _mk("video-script", "Video scripting", "content",
        ("video", "script", "storyboard", "youtube"), "standard"),
    # growth
    _mk("growth-experiment", "Growth experiments", "growth",
        ("growth", "experiment", "ab", "funnel", "conversion", "signup", "signups", "acquisition"), "standard"),
    _mk("acquisition", "Acquisition", "growth",
        ("acquisition", "campaign", "marketing", "social", "referral", "traffic", "reach", "audience"), "standard"),
    _mk("retention-analysis", "Retention", "growth",
        ("retention", "churn", "engagement", "subscribers", "readers", "mrr", "revenue"), "standard"),
    # design
    _mk("ui-design", "UI design", "design",
        ("ui", "design", "layout", "component", "mockup", "prototype"), "standard"),
    _mk("ux-research", "UX research", "design",
        ("ux", "usability", "research", "flow", "journey"), "standard"),
    _mk("visual-design", "Visual & brand", "design",
        ("visual", "brand", "logo", "illustration", "color", "identity"), "standard"),
    # data
    _mk("data-analysis", "Data analysis", "data",
        ("data", "analysis", "analyst", "metric", "metrics", "insights", "report"), "standard"),
    _mk("sql", "SQL & queries", "data",
        ("sql", "query", "warehouse", "etl"), "standard"),
    _mk("ml-modeling", "ML modeling", "data",
        ("ml", "model", "modeling", "training", "prediction", "experiment"), "deep"),
    _mk("dashboarding", "Dashboards", "data",
        ("dashboard", "chart", "visualization", "kpi", "reporting"), "cheap"),
)}


def get(skill_id: str) -> Optional[Skill]:
    return SKILLS.get(skill_id)


def keywords_for(skill_ids: Iterable[str]) -> set:
    """Union of routing keywords for the given skills. Unknown ids are skipped."""
    out: set = set()
    for sid in skill_ids or ():
        s = SKILLS.get(sid)
        if s:
            out.update(s.keywords)
    return out


def words(text) -> set:
    return {w for w in _WORD.findall(str(text or "").lower()) if len(w) > 1}


# ── evidence-based proficiency (never invented) ──────────────────────────────
def task_class_for(skill_id: str, kr_id: str = "") -> str:
    """The competency task-class a workflow step accrues evidence under.

    Compound `kr:skill` keeps per-work-stream isolation and, for system-generated KR
    ids (`krN`, which contain no ':'), does not collide with the default planner's
    bare `kr.id` — so both accrual schemes coexist (additive)."""
    skill_id = str(skill_id or "general")
    return f"{kr_id}:{skill_id}" if kr_id else skill_id


def proficiency(mem, skill_id: str, kr_id: str = "") -> Optional[float]:
    """Evidence-based proficiency for one skill on one work-stream, or None below
    the sample floor. Pure passthrough to learning.EmployeeMemory.competency — no
    new scoring math, so "insufficient evidence, never invent" is inherited."""
    if mem is None:
        return None
    return mem.competency(task_class_for(skill_id, kr_id))


def aggregate_proficiency(mem, skill_id: str) -> Optional[float]:
    """Roster-level 'how good overall at this skill' = mean of every above-floor
    `*:{skill}` (and bare `skill`) competency. None when nothing is above the floor
    (still honest — no invented aggregate). Uses only public memory surface."""
    if mem is None:
        return None
    suffix = ":" + skill_id
    classes = {ev.task_class for ev in getattr(mem, "evidence", [])
               if ev.task_class == skill_id or ev.task_class.endswith(suffix)}
    scores: List[float] = [c for c in (mem.competency(tc) for tc in classes) if c is not None]
    return round(sum(scores) / len(scores), 3) if scores else None
