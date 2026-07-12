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
                data = json.loads(resp.read(512 * 1024).decode("utf-8", "replace"))  # bounded read
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
    fns: List[SearchFn] = []
    url = os.environ.get("PO_SEARXNG_URL", "").strip()
    if url:
        fns.append(searxng_search_fn(url))
    subs = [s.strip() for s in os.environ.get("PO_REDDIT_SUBS", "").split(",") if s.strip()]
    if subs:
        fns.append(reddit_search_fn(subs))
    if not fns:
        return None                          # nothing configured → radar honestly won't scan
    return fns[0] if len(fns) == 1 else multi_search_fn(fns)


def reddit_search_fn(subreddits, *, timeout: float = 6.0, max_results: int = 8) -> SearchFn:
    """A search_fn backed by Reddit's PUBLIC `r/<sub>/hot.json` (no key). Returns recent
    hot-post titles from the given subreddits — community/consumer trends. A custom
    User-Agent is required or Reddit 429s. Fail-open: any error yields []."""
    def _clean_sub(s):
        s = str(s).strip().strip("/")
        return s[2:] if s.lower().startswith("r/") else s   # exact 'r/' prefix only (keep 'research'/'rust')
    subs = [_clean_sub(s) for s in (subreddits or []) if str(s).strip()]

    def search(_query: str) -> List[str]:
        out: List[str] = []
        for sub in subs:
            if len(out) >= max_results:
                break
            url = f"https://www.reddit.com/r/{urllib.parse.quote(sub)}/hot.json?limit=6&raw_json=1"
            req = urllib.request.Request(url, headers={"User-Agent": "pixel-office/0.1 (trend-radar)"})
            try:
                with urllib.request.urlopen(req, timeout=timeout) as resp:  # nosec - fixed public host
                    data = json.loads(resp.read(512 * 1024).decode("utf-8", "replace"))
            except Exception:
                continue   # one bad subreddit never sinks the rest (fail-open)
            for child in ((data.get("data") or {}).get("children") or []):
                title = str(((child or {}).get("data") or {}).get("title") or "").strip()
                if title:
                    out.append(f"[r/{sub}] {title}")
                if len(out) >= max_results:
                    break
        return out

    return search


def multi_search_fn(fns, *, max_results: int = 10) -> SearchFn:
    """Merge several search_fns into one — each source polled and results interleaved
    (round-robin) so no single source dominates. Fail-open per source."""
    sources = [f for f in (fns or []) if f]

    def search(query: str) -> List[str]:
        per = []
        for f in sources:
            try:
                per.append(list(f(query) or [])[:max_results])   # cap each source (bounded work)
            except Exception:
                per.append([])
        out: List[str] = []
        i = 0
        while len(out) < max_results and any(i < len(p) for p in per):
            for p in per:                    # round-robin across sources (interleave)
                if i < len(p):
                    out.append(p[i])
                    if len(out) >= max_results:
                        break
            i += 1
        return out

    return search
