"""Operating mode — the top-level dial (docs/COMPANY-LAYER.md §0.6).

Driving metaphor: the CEO drives the company; the mode is how much of the driving
the AI team does. The mode ONLY governs how much reaches the CEO and who plans —
it never caps or throttles employees (per the CEO's "no levels/limits"). The one
hard gate is an irreversible **one-way door**, which always reaches the CEO
regardless of mode.
"""
from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Tuple

DRIVES: Tuple[str, ...] = ("Manual", "Copilot", "Autopilot")
CULTURES: Tuple[str, ...] = ("Balanced", "Hyper-growth", "Steady", "Research")
SELF_TUNING: Tuple[str, ...] = ("Off", "Guardrailed", "On")
CEO_UPDATES: Tuple[str, ...] = ("Everything", "Key decisions", "Weekly digest")
RISKS: Tuple[str, ...] = ("low", "medium", "high")
_RISK_RANK = {"low": 0, "medium": 1, "high": 2}


@dataclass(frozen=True)
class OperatingMode:
    drive: str = "Copilot"
    culture: str = "Balanced"
    self_tuning: str = "Guardrailed"
    ceo_updates: str = "Key decisions"

    def validate(self) -> "OperatingMode":
        for field, allowed in (("drive", DRIVES), ("culture", CULTURES),
                               ("self_tuning", SELF_TUNING), ("ceo_updates", CEO_UPDATES)):
            if getattr(self, field) not in allowed:
                raise ValueError(f"operating_mode.{field}={getattr(self, field)!r} "
                                 f"not one of {allowed}")
        return self

    def to_dict(self) -> dict:
        return {"drive": self.drive, "culture": self.culture,
                "self_tuning": self.self_tuning, "ceo_updates": self.ceo_updates}

    @staticmethod
    def from_dict(d) -> "OperatingMode":
        if isinstance(d, str):
            return preset(d)
        if not isinstance(d, dict):
            return default()
        try:
            base = preset(str(d.get("drive") or "Copilot"))
        except ValueError:
            base = default()   # unknown/garbage drive → default, never crash
        # explicit fields override the preset defaults (everything is overridable)
        overrides = {k: d[k] for k in ("drive", "culture", "self_tuning", "ceo_updates")
                     if k in d and isinstance(d[k], str)}
        try:
            return replace(base, **overrides).validate()
        except ValueError:
            return base   # a bad override field falls back to the valid preset

    def reaches_ceo(self, *, one_way_door: bool, risk: str = "low") -> bool:
        """Does a decision reach the CEO in this mode? A one-way (irreversible)
        door ALWAYS does; reversible decisions depend on the drive mode."""
        if one_way_door:
            return True
        rank = _RISK_RANK.get(risk)
        if rank is None:
            return True   # unknown risk → fail SAFE: escalate rather than hide it
        if self.drive == "Manual":
            return rank >= _RISK_RANK["medium"]   # sees medium+ reversible calls
        if self.drive == "Copilot":
            return rank >= _RISK_RANK["high"]      # sees only high-risk reversible
        return False                               # Autopilot: reversible → never


_PRESETS = {
    "Manual":    OperatingMode("Manual", "Balanced", "Off", "Everything"),
    "Copilot":   OperatingMode("Copilot", "Balanced", "Guardrailed", "Key decisions"),
    "Autopilot": OperatingMode("Autopilot", "Hyper-growth", "On", "Weekly digest"),
}


def preset(drive: str) -> OperatingMode:
    drive = (drive or "Copilot").strip().capitalize()
    if drive not in _PRESETS:
        raise ValueError(f"unknown mode {drive!r}; choose one of {tuple(_PRESETS)}")
    return _PRESETS[drive]


def default() -> OperatingMode:
    return _PRESETS["Copilot"]
