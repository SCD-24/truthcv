"""GET /api/browser/signin-queue: derived from screenings, deduplicated by full host."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from api.main import app
from screening import store


@pytest.fixture()
def client(data_dir):
    return TestClient(app)


def _blocked(company: str, url: str, signin_url: str) -> str:
    s = store.create({"company": company, "role": "Dev", "verdict": "passed", "url": url})
    store.set_approval(s.id, "approved")
    store.record_apply_failure(
        s.id, "sign-in required", blocker="login_required", signin_url=signin_url
    )
    return s.id


def test_empty_when_nothing_is_blocked(client, data_dir):
    r = client.get("/api/browser/signin-queue")
    assert r.status_code == 200
    assert r.json() == {"sites": []}


def test_plain_failures_do_not_appear(client, data_dir):
    s = store.create({"company": "Acme", "role": "Dev", "verdict": "passed"})
    store.set_approval(s.id, "approved")
    store.record_apply_failure(s.id, "form timed out")
    r = client.get("/api/browser/signin-queue")
    assert r.json() == {"sites": []}


def test_one_blocked_posting_becomes_one_site(client, data_dir):
    _blocked(
        "Acme",
        "https://acme.wd3.myworkdayjobs.com/careers/job/1",
        "https://acme.wd3.myworkdayjobs.com/login",
    )
    sites = client.get("/api/browser/signin-queue").json()["sites"]
    assert len(sites) == 1
    assert sites[0]["host"] == "acme.wd3.myworkdayjobs.com"
    assert sites[0]["signinUrl"] == "https://acme.wd3.myworkdayjobs.com/login"
    assert sites[0]["waiting"] == 1
    assert sites[0]["companies"] == ["Acme"]


def test_many_postings_at_one_tenant_collapse_to_one_entry(client, data_dir):
    for n in (1, 2, 3):
        _blocked(
            "Acme",
            f"https://acme.wd3.myworkdayjobs.com/careers/job/{n}",
            "https://acme.wd3.myworkdayjobs.com/login",
        )
    sites = client.get("/api/browser/signin-queue").json()["sites"]
    assert len(sites) == 1
    assert sites[0]["waiting"] == 3


def test_different_tenants_of_one_platform_stay_separate(client, data_dir):
    """The unit is the full host, never the registrable domain."""
    _blocked("Acme", "https://acme.wd3.myworkdayjobs.com/j/1", "https://acme.wd3.myworkdayjobs.com/login")
    _blocked("Globex", "https://globex.wd1.myworkdayjobs.com/j/1", "https://globex.wd1.myworkdayjobs.com/login")
    sites = client.get("/api/browser/signin-queue").json()["sites"]
    hosts = sorted(s["host"] for s in sites)
    assert hosts == ["acme.wd3.myworkdayjobs.com", "globex.wd1.myworkdayjobs.com"]


def test_applied_items_drop_off_the_queue(client, data_dir):
    """Truth is the agent's experience: getting through clears the entry."""
    sid = _blocked("Acme", "https://acme.wd3.myworkdayjobs.com/j/1", "https://acme.wd3.myworkdayjobs.com/login")
    store.mark_applied(sid)
    assert client.get("/api/browser/signin-queue").json() == {"sites": []}


def test_rejected_items_drop_off_the_queue(client, data_dir):
    sid = _blocked("Acme", "https://acme.wd3.myworkdayjobs.com/j/1", "https://acme.wd3.myworkdayjobs.com/login")
    store.set_approval(sid, "rejected")
    assert client.get("/api/browser/signin-queue").json() == {"sites": []}


def test_entry_without_a_usable_signin_url_falls_back_to_the_posting(client, data_dir):
    s = store.create(
        {"company": "Acme", "role": "Dev", "verdict": "passed",
         "url": "https://acme.wd3.myworkdayjobs.com/careers/job/1"}
    )
    store.set_approval(s.id, "approved")
    store.record_apply_failure(s.id, "sign-in required", blocker="login_required")
    sites = client.get("/api/browser/signin-queue").json()["sites"]
    assert sites[0]["host"] == "acme.wd3.myworkdayjobs.com"
    assert sites[0]["signinUrl"] == "https://acme.wd3.myworkdayjobs.com/careers/job/1"


def test_unparseable_urls_are_dropped_rather_than_grouped_under_a_blank_host(client, data_dir):
    s = store.create({"company": "Acme", "role": "Dev", "verdict": "passed", "url": "not a url"})
    store.set_approval(s.id, "approved")
    store.record_apply_failure(s.id, "sign-in required", blocker="login_required")
    assert client.get("/api/browser/signin-queue").json() == {"sites": []}
