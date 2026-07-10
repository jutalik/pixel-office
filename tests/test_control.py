from pixel_office.control.approvals import ApprovalStore, classify
from pixel_office.control import deploy


# ---- classify (fail-closed risk detection) ------------------------------------

def test_classify_detects_risk_categories():
    assert "deploy" in classify("please deploy to production")
    assert "spend" in classify("buy the $50 plan")
    assert "delete" in classify("rm -rf the old data")
    assert classify("summarize this document") == []


def test_classify_is_multi_category():
    cats = classify("deploy to prod and delete the staging db")
    assert {"deploy", "delete", "prod_change"} <= set(cats)


# ---- gate: escalate-only, single-use, expiring --------------------------------

def test_declared_task_with_risky_prompt_is_escalated():
    store = ApprovalStore()
    appr = store.request("task", "svc", "let's deploy to production now", now=0)
    assert appr is not None                                   # gated, not auto-allowed
    assert "deploy" in appr.action_type.split("+")            # escalated, not "task"


def test_safe_action_needs_no_gate():
    store = ApprovalStore()
    assert store.request("task", "svc", "write a blog post", now=0) is None


def test_claim_requires_prior_approval():
    store = ApprovalStore()
    appr = store.request("deploy", "svc", "deploy", now=0)
    assert store.claim(appr.token, now=1) is None          # never approved → denied
    assert store.approve(appr.token, now=1) is True
    assert store.claim(appr.token, now=2) is not None       # now allowed


def test_single_use_no_double_spend():
    store = ApprovalStore()
    appr = store.request("deploy", "svc", "deploy", now=0)
    store.approve(appr.token, now=1)
    assert store.claim(appr.token, now=2) is not None      # first claim wins
    assert store.claim(appr.token, now=3) is None          # second is denied


def test_declared_never_shrinks_detected_risk():
    store = ApprovalStore()
    appr = store.request("deploy", "svc", "deploy then delete the staging db", now=0)
    cats = set(appr.action_type.split("+"))
    assert {"deploy", "delete"} <= cats                    # union, not just declared


def test_expiry_boundary_is_inclusive():
    store = ApprovalStore(ttl_s=10)
    appr = store.request("deploy", "svc", "deploy", now=0)
    assert store.approve(appr.token, now=10) is False       # exactly at expiry → denied
    appr2 = store.request("deploy", "svc", "deploy", now=0)
    store.approve(appr2.token, now=5)
    assert store.claim(appr2.token, now=10) is None         # claim exactly at expiry → denied
    # a fresh approval claimed just inside TTL DOES succeed (real check, not vacuous)
    appr3 = store.request("deploy", "svc", "deploy", now=0)
    store.approve(appr3.token, now=5)
    assert store.claim(appr3.token, now=9) is not None


def test_expired_approval_is_denied():
    store = ApprovalStore(ttl_s=10)
    appr = store.request("deploy", "svc", "deploy", now=0)
    store.approve(appr.token, now=1)
    assert store.claim(appr.token, now=100) is None        # past TTL


def test_audit_never_stores_prompt_text():
    store = ApprovalStore()
    secret_prompt = "deploy the SUPER-SECRET-KEY-42 service"
    store.request("deploy", "svc", secret_prompt, now=0)
    for rec in store.audit:
        assert "SUPER-SECRET-KEY-42" not in rec.prompt_hash
        assert len(rec.prompt_hash) == 16  # a hash, not the text


def test_audit_records_lifecycle():
    store = ApprovalStore()
    appr = store.request("delete", "svc", "delete the db", now=0)
    store.approve(appr.token, now=1)
    store.claim(appr.token, now=2)
    decisions = [r.decision for r in store.audit]
    assert decisions == ["requested", "approved", "consumed"]


def test_concurrent_claims_single_winner():
    import threading
    store = ApprovalStore()
    appr = store.request("deploy", "svc", "deploy", now=0)
    store.approve(appr.token, now=1)
    wins = []

    def worker():
        if store.claim(appr.token, now=2) is not None:
            wins.append(1)

    threads = [threading.Thread(target=worker) for _ in range(20)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert sum(wins) == 1  # atomic under the lock — exactly one winner


# ---- deploy detection ---------------------------------------------------------

def test_deploy_plan_shape():
    plan = deploy.detect()
    assert plan.localhost is True
    assert plan.recommendation in ("localhost", "docker") or plan.recommendation.startswith("tunnel:")
    assert isinstance(plan.tunnels, list)
    assert isinstance(plan.reachable_from_phone, bool)
