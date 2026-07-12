import json

import pixel_office.company.search as search


def test_default_search_fn_is_none_without_env(monkeypatch):
    monkeypatch.delenv("PO_SEARXNG_URL", raising=False)
    assert search.default_search_fn() is None


def test_default_search_fn_wired_when_configured(monkeypatch):
    monkeypatch.setenv("PO_SEARXNG_URL", "http://localhost:8888")
    assert callable(search.default_search_fn())


class _Resp:
    def __init__(self, payload):
        self._p = payload

    def read(self, n=-1):
        return json.dumps(self._p).encode()

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def test_searxng_returns_result_titles(monkeypatch):
    payload = {"results": [{"title": "AI trend one"}, {"title": ""}, {"title": "AI trend two"}]}
    monkeypatch.setattr(search.urllib.request, "urlopen", lambda req, timeout=0: _Resp(payload))
    fn = search.searxng_search_fn("http://x:8888/", max_results=5)
    assert fn("q") == ["AI trend one", "AI trend two"]      # blank titles skipped


def test_searxng_fails_open_on_network_error(monkeypatch):
    def boom(req, timeout=0):
        raise OSError("network down")
    monkeypatch.setattr(search.urllib.request, "urlopen", boom)
    assert search.searxng_search_fn("http://x")("q") == []


def test_empty_base_url_is_a_noop():
    assert search.searxng_search_fn("")("q") == []


def test_reddit_returns_prefixed_hot_titles(monkeypatch):
    payload = {"data": {"children": [{"data": {"title": "AI agents are eating SaaS"}},
                                     {"data": {"title": ""}},
                                     {"data": {"title": "New retention playbook"}}]}}
    monkeypatch.setattr(search.urllib.request, "urlopen", lambda req, timeout=0: _Resp(payload))
    got = search.reddit_search_fn(["startups"])("q")
    assert got == ["[r/startups] AI agents are eating SaaS", "[r/startups] New retention playbook"]


def test_reddit_fails_open_per_subreddit(monkeypatch):
    def boom(req, timeout=0):
        raise OSError("429")
    monkeypatch.setattr(search.urllib.request, "urlopen", boom)
    assert search.reddit_search_fn(["startups", "ml"])("q") == []   # both fail → [] (never raises)


def test_multi_search_interleaves_sources_round_robin():
    a = lambda q: ["a1", "a2", "a3"]
    b = lambda q: ["b1", "b2"]
    assert search.multi_search_fn([a, b], max_results=5)("q") == ["a1", "b1", "a2", "b2", "a3"]


def test_default_search_composes_configured_sources(monkeypatch):
    monkeypatch.setenv("PO_SEARXNG_URL", "http://localhost:8888")
    monkeypatch.setenv("PO_REDDIT_SUBS", "startups, machinelearning")
    assert callable(search.default_search_fn())          # both sources → one merged feed


def test_default_search_none_when_nothing_configured(monkeypatch):
    monkeypatch.delenv("PO_SEARXNG_URL", raising=False)
    monkeypatch.delenv("PO_REDDIT_SUBS", raising=False)
    assert search.default_search_fn() is None            # honest: no source → no scanning
