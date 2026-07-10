"""Build a Company from a `po new` manifest (pixel-office.json).

Closes the loop: `po new` records the objective (goal), operating mode, and roles;
this turns that into a live Company (employees from roles, OKRs from the goal).
KRs are NOT fabricated — they come from planning; the objective starts at 0%
honestly until Key Results are set.
"""
from __future__ import annotations

import re

from .company import Company
from .employee import Employee
from .mode import OperatingMode

_SLUG = re.compile(r"[^a-z0-9]+")


def _slug(s: str) -> str:
    return _SLUG.sub("-", str(s).strip().lower()).strip("-") or "role"


def build_company(manifest: dict, *, sink=None, host_id: str = "local") -> Company:
    if not isinstance(manifest, dict):
        manifest = {}
    name = manifest.get("name") or manifest.get("slug") or "company"
    objective = manifest.get("goal") or manifest.get("what") or "grow the company"
    mode = OperatingMode.from_dict(manifest.get("mode"))
    company = Company(str(name), str(objective), mode=mode, host_id=host_id, sink=sink)

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
        for i in range(count):
            eid = base if count == 1 else f"{base}-{i + 1}"
            while eid in seen:
                eid += "x"
            seen.add(eid)
            company.team.hire(Employee(eid, str(title)))
    return company
