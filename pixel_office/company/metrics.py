"""Growth loop — move OKRs from a live product's REAL metrics (docs/COMPANY-LAYER.md).

A scaffolded product exposes `/api/telemetry|funnel|quality|growth`. When a company
knows its product's base URL (`PO_PRODUCT_URL`, or a manifest `product_url`), the
autonomy loop polls those endpoints on a cadence and feeds the flat numbers into
`okr.apply_metrics` — so a KR only advances from a metric it actually names. Unset →
no poll (honest: OKRs stay at 0% until real metrics land). Stdlib only, fail-open.
"""
from __future__ import annotations

import json
import os
import urllib.request
from typing import Dict

_KPI_PATHS = ("/api/telemetry", "/api/funnel", "/api/quality", "/api/growth")
_MAX_BODY = 256 * 1024   # bounded read (a misbehaving product can't OOM us)


def fetch_metrics(base_url: str, *, timeout: float = 4.0) -> Dict[str, float]:
    """Flat {metric_name: number} scraped from the product's KPI surface. Only
    finite numeric leaf values are kept; everything else (nested/strings) is ignored.
    Fail-open per endpoint — one bad endpoint never sinks the rest."""
    base = str(base_url or "").rstrip("/")
    if not base:
        return {}
    out: Dict[str, float] = {}
    for path in _KPI_PATHS:
        try:
            with urllib.request.urlopen(base + path, timeout=timeout) as resp:  # nosec - user-configured host
                data = json.loads(resp.read(_MAX_BODY).decode("utf-8", "replace"))
        except Exception:
            continue
        if isinstance(data, dict):
            for k, v in data.items():
                if isinstance(v, (int, float)) and not isinstance(v, bool) and v == v and abs(v) != float("inf"):
                    out[str(k)] = float(v)
    return out


def product_url_for(manifest=None) -> str:
    """The product base URL to poll: a manifest `product_url`, else `PO_PRODUCT_URL`,
    else '' (no growth-loop polling)."""
    if isinstance(manifest, dict) and manifest.get("product_url"):
        return str(manifest["product_url"]).strip()
    return os.environ.get("PO_PRODUCT_URL", "").strip()
