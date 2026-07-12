"""Workflows — reusable playbooks a company follows to ship real work
(docs/COMPANY-LAYER.md).

A workflow is an ordered list of steps; each step names the skill (or, as a
fallback, the role family) it needs, so the dispatcher can route each step to the
best-skilled employee. Workflows are how "run a service the right way" becomes
mechanical: spec → architecture → implement → test → review → deploy.

Honesty: a workflow never fabricates progress. Steps advance only on a real
`TaskResult.ok` (see company.advance_workflow); `for_kr` returns None on an
ambiguous match rather than guessing.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, Optional, Tuple

from . import skills as _skills

_FAMILY_WORDS = {
    "engineering": {"engineer", "engineering", "feature", "features", "api", "backend",
                    "frontend", "service", "bug", "deploy", "code", "performance", "latency"},
    "content": {"content", "write", "writing", "article", "post", "blog", "recipe",
                "editor", "seo", "story", "newsletter"},
    "growth": {"growth", "signup", "signups", "user", "users", "acquisition", "retention",
               "churn", "campaign", "audience", "subscribers", "conversion", "reach"},
    "design": {"design", "ui", "ux", "brand", "visual", "mockup", "prototype"},
    "data": {"data", "analysis", "analyst", "metric", "metrics", "dashboard", "model", "insights"},
}


@dataclass(frozen=True)
class Step:
    name: str
    skill: str = ""     # a skills.SKILLS id (preferred routing signal)
    family: str = ""    # fallback family when no specific skill
    tier: str = ""      # optional per-step tier override


@dataclass(frozen=True)
class Workflow:
    id: str
    title: str
    steps: Tuple[Step, ...]


@dataclass
class WorkflowRun:
    """Live per-KR progress through a workflow. Mutated only by company.advance_workflow
    on a real TaskResult — steps never advance without evidence."""
    kr_id: str
    workflow_id: str
    step_index: int = 0
    done: bool = False
    blocked: bool = False   # last step failed → halt until company.clear_workflow(kr_id)


def _wf(id, title, steps) -> Workflow:
    return Workflow(id=id, title=title, steps=tuple(steps))


WORKFLOWS: Dict[str, Workflow] = {w.id: w for w in (
    _wf("ship-feature", "Ship a feature", [
        Step("spec", "api-design"),
        Step("architecture", "system-design"),
        Step("implement", "backend-impl"),
        Step("test", "testing"),
        Step("review", "code-review"),
        Step("deploy", "devops-ci"),
    ]),
    _wf("content-pipeline", "Content pipeline", [
        Step("research", family="content"),
        Step("draft", "copywriting"),
        Step("edit", "content-editing"),
        Step("seo", "seo"),
        Step("publish", family="content"),
    ]),
    _wf("architecture-review", "Architecture review", [
        Step("gather", "system-design"),
        Step("analyze-tradeoffs", "tradeoff-analysis"),
        Step("decide", family="engineering"),
        Step("document", "architecture-review"),
    ]),
    _wf("growth-experiment", "Growth experiment", [
        Step("hypothesis", "growth-experiment"),
        Step("instrument", "data-analysis"),
        Step("run", "growth-experiment"),
        Step("analyze", "data-analysis"),
        Step("decide", family="growth"),
    ]),
    _wf("incident-response", "Incident response", [
        Step("detect", family="engineering"),
        Step("triage", "devops-ci"),
        Step("mitigate", "backend-impl"),
        Step("verify", "testing"),
        Step("postmortem", "architecture-review"),
    ]),
)}


def get(workflow_id: str) -> Optional[Workflow]:
    return WORKFLOWS.get(workflow_id)


# Special-purpose workflows win on their own explicit trigger words (checked first);
# otherwise a KR maps to the default workflow for its dominant role family.
_SPECIAL = (
    ("incident-response", {"incident", "outage", "downtime", "postmortem", "sev", "oncall"}),
    ("architecture-review", {"architecture", "rearchitect", "redesign", "adr", "tradeoff", "tradeoffs"}),
)
_FAMILY_WF = {
    "engineering": "ship-feature",
    "content": "content-pipeline",
    "growth": "growth-experiment",
    "data": "growth-experiment",
    "design": "ship-feature",
}


def for_kr(kr) -> Optional[str]:
    """Pick the workflow for a Key Result: an explicit special-purpose trigger word
    wins first, else the KR's dominant role family maps to its default workflow.
    Returns None when nothing matches or the top two families tie (ambiguous → let
    the caller fall back to the plain planner; never a confident-wrong pick)."""
    text = getattr(kr, "text", "") or ""
    metric = getattr(kr, "metric", "") or ""
    words = _skills.words(text + " " + metric)
    if not words:
        return None
    for wid, trig in _SPECIAL:
        if words & trig:
            return wid
    scored = sorted(((len(words & fw), fam) for fam, fw in _FAMILY_WORDS.items()),
                    key=lambda t: (t[0], t[1]), reverse=True)
    if not scored or scored[0][0] == 0:
        return None
    if len(scored) > 1 and scored[1][0] == scored[0][0]:
        return None   # ambiguous — two families fit equally well
    return _FAMILY_WF.get(scored[0][1])
