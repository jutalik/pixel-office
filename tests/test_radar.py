"""Company Layer Phase 6 — budgeted trend radar."""
from pixel_office.company.radar import TrendRadar


def test_query_from_niche_and_objective():
    r = TrendRadar(objective="be #1 recipe blog", niche="busy parents")
    q = r.query()
    assert "busy parents" in q and "recipe blog" in q


def test_scan_dedupes_across_runs():
    calls = {"n": 0}

    def search(q):
        calls["n"] += 1
        return ["AI recipes", "meal kits", "ai recipes", "  Meal Kits  "]   # dupes/case/space

    r = TrendRadar(objective="grow", search_fn=search, min_interval_s=0)
    first = r.scan(now=0)
    assert first.trends == ["AI recipes", "meal kits"]     # deduped, trimmed
    second = r.scan(now=100)                                 # same items, still current → same set
    assert second.trends == ["AI recipes", "meal kits"] and calls["n"] == 2


def test_stale_trend_expires_after_ttl_so_current_means_recent():
    calls = [0]
    def search(q):
        calls[0] += 1
        return ["AI recipes"] if calls[0] == 1 else []   # trending once, then gone
    r = TrendRadar(objective="grow", search_fn=search, min_interval_s=0, trend_ttl_s=1000)
    assert r.scan(now=0).trends == ["AI recipes"]
    assert r.scan(now=500).trends == ["AI recipes"]     # within TTL → still current
    assert r.scan(now=2000).trends == []                # not seen again + past TTL → expired


def test_cadence_gate_is_the_budget():
    r = TrendRadar(objective="grow", search_fn=lambda q: ["x"], min_interval_s=1000)
    assert r.scan(now=0).ran is True
    skipped = r.scan(now=500)                                # within the interval
    assert skipped.ran is False and skipped.trends == []
    assert r.scan(now=2000).ran is True                     # past the interval


def test_scan_fails_open_on_search_error():
    r = TrendRadar(objective="grow", search_fn=lambda q: 1 / 0, min_interval_s=0)
    rep = r.scan(now=0)
    assert rep.ran is True and rep.trends == []              # error → empty, not a crash


def test_no_search_fn_is_safe():
    r = TrendRadar(objective="grow", min_interval_s=0)
    assert r.scan(now=0).trends == []


def test_max_trends_cap():
    r = TrendRadar(objective="g", search_fn=lambda q: [f"t{i}" for i in range(50)],
                   min_interval_s=0, max_trends=5)
    assert len(r.scan(now=0).trends) == 5
    r0 = TrendRadar(objective="g", search_fn=lambda q: ["a", "b"], min_interval_s=0, max_trends=0)
    assert r0.scan(now=0).trends == []      # a zero cap yields nothing
