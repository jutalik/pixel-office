"""Render a manifest into a real project directory on disk.

Safety: writes ONLY inside the target project dir; refuses to overwrite a
non-empty existing dir (never clobbers a user's work); paths are contained
(no traversal out of the root). No manifest field is ever executed.
"""
from __future__ import annotations

import shutil
from pathlib import Path
from typing import Dict

from . import templates
from .manifest import Manifest


def _context(m: Manifest) -> dict:
    return {
        "title": m.name, "pitch": m.what, "goal": m.goal, "niche": m.niche,
        "stack": m.stack, "benchmarks": list(m.benchmarks),
    }


def plan(m: Manifest) -> Dict[str, str]:
    """The files that would be written (path -> content). Pure, no disk I/O."""
    files = dict(templates.render(m.stack, _context(m)))
    files["pixel-office.json"] = _manifest_json(m)
    return files


def _manifest_json(m: Manifest) -> str:
    import json
    return json.dumps({
        "name": m.name, "slug": m.slug, "what": m.what, "goal": m.goal,
        "niche": m.niche, "stack": m.stack, "benchmarks": list(m.benchmarks),
        "roles": [{"title": r.title, "count": r.count} for r in m.roles],
        "mode": m.mode.to_dict(),
    }, indent=2) + "\n"


def build(m: Manifest, root: Path) -> Path:
    """Create the project under root/<slug>. Returns the project dir."""
    root = Path(root)
    project = (root / m.slug).resolve()
    if project.parent != root.resolve() and root.resolve() not in project.parents:
        raise ValueError("refusing to write outside the target root")
    if project.exists() and any(project.iterdir()):
        raise FileExistsError(f"{project} exists and is not empty — refusing to overwrite")
    pre_existing = project.exists()
    files = plan(m)
    try:
        for rel, content in files.items():
            dest = (project / rel).resolve()
            if root.resolve() not in dest.parents:
                raise ValueError(f"path escapes project root: {rel}")
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_text(content)
    except Exception:
        # clean up our own partial output so a retry isn't blocked. The guard
        # above guarantees the dir was empty, so restoring it to empty (or
        # removing it if we created it) only ever removes po's own writes.
        if pre_existing:
            for child in list(project.iterdir()):
                if child.is_dir():
                    shutil.rmtree(child, ignore_errors=True)
                else:
                    try:
                        child.unlink()
                    except OSError:
                        pass
        else:
            shutil.rmtree(project, ignore_errors=True)
        raise
    return project
