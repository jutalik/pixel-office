"""The PO — turns a decision into a CEO card in 5W1H (docs/COMPANY-LAYER.md §6).

Deterministic composition from the memo's own fields (no LLM call). The PO is a
presentation boundary: it explains WHY (tied to the goal), WHAT exactly, and the
reversibility/risk, with a recommended choice — so a busy CEO decides in seconds.
"""
from __future__ import annotations

from .memo import DecisionMemo


def decision_card(memo: DecisionMemo, *, objective: str = "") -> dict:
    door = "one-way (irreversible)" if memo.one_way_door else "two-way (reversible)"
    return {
        "id": memo.id,
        "decision": memo.title,                     # one-line
        "recommendation": memo.decision,            # what the DRI recommends
        "risk": memo.risk,
        "reversibility": door,
        "one_way_door": memo.one_way_door,
        # 5W1H (collapsed by default in the UI)
        "who": memo.dri,                            # the accountable owner
        "what": memo.decision,
        "why": memo.rationale or (f"advances: {objective}" if objective else "advances the goal"),
        "how": f"{'requires your sign-off — irreversible' if memo.one_way_door else 'reversible; proceeds on approval'}",
        "status": memo.status,
    }
