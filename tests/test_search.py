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

    def read(self):
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
