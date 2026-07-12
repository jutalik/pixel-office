"""Route a task to the right employee (docs/COMPANY-LAYER.md §3).

Deterministic, zero-token, evidence-first. Picks the owner for a Key Result by:
  1. role fit — how many of the KR's words fall in the employee's role families
     (a small domain keyword map, so "reach 1000 signups" routes to a *marketer*,
     "publish recipes" to a *writer*, not always the first hire);
  2. proven competency for that exact work-stream (kr.id) nudges toward whoever
     has a real track record — never an invented score (below the sample floor
     it contributes nothing);
  3. load — ties break toward the lighter-loaded employee, then insertion order,
     so work spreads instead of piling on one identity.

No role match for anyone → fall back to the lightest-loaded employee (still
assigned + spread), never a crash.
"""
from __future__ import annotations

import re
from typing import Optional

from . import skills as _skills
from .employee import Employee

_WORD = re.compile(r"[a-z0-9]+")
# words that carry no routing signal — dropped before matching
_STOP = {"the", "a", "an", "to", "of", "and", "for", "with", "by", "our", "into",
         "reach", "publish", "ship", "launch", "grow", "build", "make", "increase",
         "get", "hit", "drive", "deliver", "improve", "add", "new", "per", "week", "month"}

# role family -> signal words that indicate this kind of work. Each set also
# includes the role-TITLE words for that family (engineer/writer/…) so a plain
# title like "software engineer" activates the family, not just KR keywords.
ROLE_FAMILIES = {
    "engineering": {"engineer", "engineering", "developer", "dev", "programmer", "swe",
                    "sre", "devops", "platform", "backend", "frontend", "fullstack", "api",
                    "feature", "features", "bug", "bugs", "deploy", "infra", "infrastructure",
                    "code", "service", "services", "endpoint", "database", "db",
                    "performance", "latency", "uptime", "test"},
    "content": {"content", "writer", "write", "writing", "editor", "copywriter", "journalist",
                "recipe", "recipes", "article", "articles", "blog", "post", "posts", "copy",
                "seo", "editorial", "story", "stories", "newsletter", "video", "videos", "script"},
    "growth": {"growth", "marketing", "marketer", "signup", "signups", "user", "users",
               "acquisition", "retention", "churn", "campaign", "social", "audience",
               "subscribers", "readers", "reach", "traffic", "conversion", "referral", "mrr", "revenue"},
    "design": {"design", "designer", "ui", "ux", "brand", "visual", "visuals", "mockup",
               "prototype", "logo", "illustration"},
    "data": {"data", "analyst", "analytics", "scientist", "metric", "metrics", "dashboard",
             "experiment", "experiments", "ab", "model", "ml", "insights", "report", "reports"},
}


def _words(s) -> set:
    return {w for w in _WORD.findall(str(s or "").lower()) if w not in _STOP and len(w) > 2}


def _families_of(emp: Employee) -> set:
    """Which role families this employee's title/persona belong to."""
    tw = _words(emp.title) | _words(emp.persona)
    fams = {fam for fam, kws in ROLE_FAMILIES.items() if tw & kws}
    # also treat a literal title word as its own signal (e.g. "recipe editor")
    return fams


# stable priority + display label for the department an employee belongs to
_DEPT_ORDER = ("engineering", "content", "growth", "design", "data")
_DEPT_LABELS = {"engineering": "Engineering", "content": "Content", "growth": "Growth",
                "design": "Design", "data": "Data"}


def department_of(emp: Employee) -> str:
    """A display department for the office floor. Deterministic; unmatched roles
    land in a shared 'Team' room rather than being hidden."""
    fams = _families_of(emp)
    for fam in _DEPT_ORDER:
        if fam in fams:
            return _DEPT_LABELS[fam]
    return "Team"


def _emp_keywords(emp: Employee) -> set:
    kws = set()
    for fam in _families_of(emp):
        kws |= ROLE_FAMILIES[fam]
    kws |= _words(emp.title)   # the title words themselves count as fit signals
    kws |= _skills.keywords_for(getattr(emp, "skills", ()))   # explicit skills sharpen fit (empty for title-only)
    return kws


def role_fit(kr, emp: Employee) -> int:
    kr_words = _words(getattr(kr, "text", "")) | _words(getattr(kr, "metric", ""))
    return len(kr_words & _emp_keywords(emp))


def best_owner(company, kr) -> Optional[Employee]:
    team = company.team.all()
    if not team:
        return None

    def key(emp):
        mem = company.runtime.memory_of(emp.id)
        comp = mem.competency(str(getattr(kr, "id", ""))) or 0.0  # str: unhashable id can't crash
        load = len(mem.evidence)                              # total work done so far
        # higher fit, then higher proven competency, then lighter load
        return (role_fit(kr, emp), comp, -load)

    # max is stable → ties fall to insertion (hire) order, keeping routing deterministic
    return max(team, key=key)


def best_owner_for_step(company, kr, step) -> Optional[Employee]:
    """Route ONE workflow step to the best-skilled employee. Fit = overlap with the
    step's skill keywords (or its family fallback); tie-break on evidence-based
    proficiency for that skill on this KR (never invented — None → 0.0), then load."""
    team = company.team.all()
    if not team:
        return None
    step_kw = _skills.keywords_for([step.skill]) if getattr(step, "skill", "") \
        else ROLE_FAMILIES.get(getattr(step, "family", ""), set())
    kr_id = str(getattr(kr, "id", ""))

    def key(emp):
        mem = company.runtime.memory_of(emp.id)
        fit = len(step_kw & _emp_keywords(emp))
        prof = (_skills.proficiency(mem, step.skill, kr_id) or 0.0) if getattr(step, "skill", "") else 0.0
        return (fit, prof, -len(mem.evidence))

    return max(team, key=key)
