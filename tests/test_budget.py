import threading

import pytest

from pixel_office.control.budget import BudgetGuard


def test_charge_within_cap():
    b = BudgetGuard(10.0)
    assert b.charge(4.0) is True
    assert b.remaining() == 6.0


def test_charge_over_cap_is_blocked_and_not_recorded():
    b = BudgetGuard(10.0)
    b.charge(8.0)
    assert b.charge(5.0) is False        # would exceed → blocked
    assert b.remaining() == 2.0          # not recorded
    assert b.charge(2.0) is True         # exact fit ok


def test_would_exceed_preflight():
    b = BudgetGuard(10.0)
    b.charge(9.0)
    assert b.would_exceed(2.0) is True
    assert b.would_exceed(1.0) is False


def test_per_scope_cap():
    b = BudgetGuard(100.0, per_scope_cap_usd=5.0)
    assert b.charge(5.0, scope="svcA") is True
    assert b.charge(1.0, scope="svcA") is False   # per-scope cap hit
    assert b.charge(5.0, scope="svcB") is True     # other scope independent


def test_negative_and_nonfinite_rejected():
    for bad in (-1, float("nan"), float("inf")):
        with pytest.raises(ValueError):
            BudgetGuard(bad)
        with pytest.raises(ValueError):
            BudgetGuard(10).charge(bad)


def test_nonfinite_would_exceed_is_fail_closed():
    b = BudgetGuard(10)
    assert b.would_exceed(float("nan")) is True
    assert b.would_exceed(float("inf")) is True


def test_concurrent_charges_never_exceed_cap():
    b = BudgetGuard(100.0)
    ok = []

    def worker():
        if b.charge(1.0):
            ok.append(1)

    threads = [threading.Thread(target=worker) for _ in range(500)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert sum(ok) == 100                # exactly cap/cost successes, no overspend
    assert b.state().spent_usd == 100.0
