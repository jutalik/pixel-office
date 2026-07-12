"""Pluggable web search for the trend radar — bring your own engine (local-first).

A self-hosted **SearXNG** instance is the recommended default: set `PO_SEARXNG_URL`
to your instance (e.g. `http://127.0.0.1:8888`) and the company's radar researches
your domain through it — no API key, no third-party sees your queries. If nothing
is configured the radar simply does not scan (honest: no fabricated trends). Uses
only the standard library, so it adds no dependency.
"""
from __future__ import annotations

import json
import os
import urllib.parse
import urllib.request
from typing import Callable, List, Optional

SearchFn = Callable[[str], List[str]]


def searxng_search_fn(base_url: str, *, timeout: float = 6.0, max_results: int = 8) -> SearchFn:
    """A search_fn backed by a SearXNG JSON endpoint. Returns short result titles
    (headlines only — no bodies stored). Fail-open: a bad response yields []."""
    base = str(base_url or "").rstrip("/")

    def search(query: str) -> List[str]:
        if not base:
            return []
        url = base + "/search?" + urllib.parse.urlencode({"q": query, "format": "json"})
        req = urllib.request.Request(url, headers={"User-Agent": "pixel-office/0.1"})
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:  # nosec - user-configured host
                data = json.loads(resp.read().decode("utf-8", "replace"))
        except Exception:
            return []   # network/parse error is not fatal — the radar fails open
        out: List[str] = []
        for r in (data.get("results") or []):
            title = str((r or {}).get("title") or "").strip()
            if title:
                out.append(title)
            if len(out) >= max_results:
                break
        return out

    return search


def default_search_fn() -> Optional[SearchFn]:
    """The configured search_fn, or None when the user hasn't added an engine.
    Reads `PO_SEARXNG_URL` (a self-hosted SearXNG). Kept a function so tests and
    `po run` share one wiring point."""
    url = os.environ.get("PO_SEARXNG_URL", "").strip()
    return searxng_search_fn(url) if url else None
