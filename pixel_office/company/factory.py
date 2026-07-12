"""Build a Company from a `po new` manifest (pixel-office.json).

Closes the loop: `po new` records the objective (goal), operating mode, roles,
and any starting Key Results; this turns that into a live Company (employees from
roles, OKRs from the goal + the user's KRs). KRs are NOT fabricated — they are
either what the user set at init or empty; the objective stays at 0% honestly
until real progress lands.
"""
from __future__ import annotations

import math
import re

from . import roles as _roles
from .company import Company
from .employee import Employee
from .mode import OperatingMode
from .metrics import product_url_for as _product_url_for
from .okr import KeyResult
from .search import default_search_fn as _default_search_fn

_SLUG = re.compile(r"[^a-z0-9]+")


def _slug(s: str) -> str:
    return _SLUG.sub("-", str(s).strip().lower()).strip("-") or "role"


def _seed_krs(company: Company, manifest: dict) -> None:
    """Seed user-provided Key Results (from the manifest) into the OKR tree.
    Malformed entries are skipped, not fabricated — a bad KR never wedges boot."""
    raw = manifest.get("key_results")
    raw = raw if isinstance(raw, (list, tuple)) else []
    for i, k in enumerate(raw):
        if not isinstance(k, dict):
            continue
        text = str(k.get("text") or "").strip()
        if not text:
            continue
        try:
            target = float(k.get("target", 1.0))
        except (TypeError, ValueError):
            target = 1.0
        if not math.isfinite(target) or target <= 0:
            target = 1.0
        cadence = str(k.get("cadence") or "weekly").strip().lower()
        if cadence not in ("weekly", "monthly"):
            cadence = "weekly"
        try:
            company.okrs.add_kr(KeyResult(id=f"kr{i + 1}", text=text[:120], target=target,
                                          cadence=cadence, metric=str(k.get("metric") or "")[:40]))
        except ValueError:
            pass   # duplicate id / bad cadence — skip, don't crash the build


def build_company(manifest: dict, *, sink=None, host_id: str = "local") -> Company:
    if not isinstance(manifest, dict):
        manifest = {}
    name = manifest.get("name") or manifest.get("slug") or "company"
    objective = manifest.get("goal") or manifest.get("what") or "grow the company"
    mode = OperatingMode.from_dict(manifest.get("mode"))
    # radar research runs through the user's own search engine (SearXNG via
    # PO_SEARXNG_URL); unset → no scan (honest, no fabricated trends).
    company = Company(str(name), str(objective), mode=mode, host_id=host_id, sink=sink,
                      niche=str(manifest.get("niche") or ""), search_fn=_default_search_fn())
    company.product_url = _product_url_for(manifest)   # growth loop polls this (PO_PRODUCT_URL / manifest)
    _seed_krs(company, manifest)

    raw_roles = manifest.get("roles")
    raw_roles = raw_roles if isinstance(raw_roles, (list, tuple)) else []
    seen = set()
    for role in raw_roles:
        title = (role.get("title") if isinstance(role, dict) else str(role)) or "member"
        try:
            count = max(1, min(20, int(role.get("count", 1)))) if isinstance(role, dict) else 1
        except (TypeError, ValueError):
            count = 1
        base = _slug(title)
        spec = _roles.match_title(str(title))   # resolve free-text title → library role (None if unclear)
        for i in range(count):
            eid = base if count == 1 else f"{base}-{i + 1}"
            while eid in seen:
                eid += "x"
            seen.add(eid)
            if spec:   # keep the user's title (additive); enrich with role/skills/workflows/persona/tier
                company.team.hire(Employee(eid, str(title), persona=spec.persona, tier=spec.tier,
                                           skills=spec.skills, role=spec.id, workflows=spec.workflows))
            else:
                company.team.hire(Employee(eid, str(title)))
    return company
