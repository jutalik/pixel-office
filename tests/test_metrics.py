import json

import pixel_office.company.metrics as metrics


class _R:
    def __init__(self, p):
        self.p = p

    def read(self, n=-1):
        return json.dumps(self.p).encode()

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def test_fetch_metrics_flattens_numeric_leaves(monkeypatch):
    payloads = {"/api/telemetry": {"requests": 10, "error_rate": 0.0},
                "/api/growth": {"subscribers": 40, "channels": {}}}

    def fake(url, timeout=0):
        for p, d in payloads.items():
            if url.endswith(p):
                return _R(d)
        return _R({})

    monkeypatch.setattr(metrics.urllib.request, "urlopen", fake)
    m = metrics.fetch_metrics("http://x:8000")
    assert m["requests"] == 10.0 and m["subscribers"] == 40.0
    assert "channels" not in m           # nested dicts are skipped, only numeric leaves


def test_conflicting_metric_across_endpoints_is_dropped_not_last_write(monkeypatch):
    # two endpoints report the SAME name with DIFFERENT values → ambiguous → dropped,
    # so okr.apply_metrics never trusts an arbitrary last-write.
    payloads = {"/api/telemetry": {"users": 10, "requests": 5},
                "/api/growth": {"users": 999}}

    def fake(url, timeout=0):
        for p, d in payloads.items():
            if url.endswith(p):
                return _R(d)
        return _R({})

    monkeypatch.setattr(metrics.urllib.request, "urlopen", fake)
    m = metrics.fetch_metrics("http://x")
    assert "users" not in m              # conflicting → dropped entirely
    assert m["requests"] == 5.0          # non-conflicting names survive


def test_same_value_across_endpoints_is_kept(monkeypatch):
    payloads = {"/api/telemetry": {"users": 42}, "/api/growth": {"users": 42}}

    def fake(url, timeout=0):
        for p, d in payloads.items():
            if url.endswith(p):
                return _R(d)
        return _R({})

    monkeypatch.setattr(metrics.urllib.request, "urlopen", fake)
    assert metrics.fetch_metrics("http://x")["users"] == 42.0   # agreement is fine


def test_fetch_metrics_empty_url_is_noop():
    assert metrics.fetch_metrics("") == {}


def test_fetch_metrics_fails_open(monkeypatch):
    def boom(url, timeout=0):
        raise OSError("down")
    monkeypatch.setattr(metrics.urllib.request, "urlopen", boom)
    assert metrics.fetch_metrics("http://x") == {}


def test_product_url_for_precedence(monkeypatch):
    monkeypatch.delenv("PO_PRODUCT_URL", raising=False)
    assert metrics.product_url_for({}) == ""
    assert metrics.product_url_for({"product_url": "http://p"}) == "http://p"
    monkeypatch.setenv("PO_PRODUCT_URL", "http://env")
    assert metrics.product_url_for({}) == "http://env"
