"""screening.jev: question construction, threshold mapping, fail-open, enabled().

The HTTP layer is always mocked here — this suite must never make a live
call to Jev.
"""

from __future__ import annotations

import http.client
import json
import urllib.error

import pytest

import secretstore
from agentconfig.store import JobProfile
from screening import jev

FERNET_KEY = "h2oN5GQVeWVhciVjWNImtAmWFyPGlrWvDCq8vXuqfmo="


@pytest.fixture(autouse=True)
def _encryption_key(monkeypatch):
    """set_connection requires ENCRYPTION_KEY; every test here may write one."""
    monkeypatch.setenv("ENCRYPTION_KEY", FERNET_KEY)


class _FakeResponse:
    def __init__(self, body):
        self._body = json.dumps(body).encode()
        self._read_error = None

    def read(self):
        if self._read_error is not None:
            raise self._read_error
        return self._body

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def _install_fake_urlopen(monkeypatch, handler):
    """Patch urllib.request.urlopen with a handler(request) -> response|exception.

    ``handler`` may also return a ``(body, read_error)`` pair, where
    ``read_error`` is an exception to raise from ``response.read()`` instead
    of returning ``body``.
    """

    def fake_urlopen(request, timeout=None):
        result = handler(request)
        if isinstance(result, Exception):
            raise result
        if isinstance(result, tuple):
            body, read_error = result
            response = _FakeResponse(body)
            response._read_error = read_error
            return response
        return _FakeResponse(result)

    monkeypatch.setattr(jev.urllib.request, "urlopen", fake_urlopen)


@pytest.fixture()
def full_profile():
    return JobProfile(
        name="p",
        enabled=True,
        keywords=["backend"],
        rejected_role_types=["internship"],
        salary_floor=100000,
        currency="USD",
        employment_country="Canada",
        eor_allowed=False,
        remote_model="remote",
    )


# --- enabled() truth table ---------------------------------------------


def test_enabled_false_with_no_key(data_dir):
    assert jev.enabled() is False


def test_enabled_false_with_key_but_no_toggle(data_dir):
    secretstore.set_connection("jev", {"apiKey": "jev_secret"})
    assert jev.enabled() is False


def test_enabled_false_with_toggle_but_no_key(data_dir):
    secretstore.set_connection("jev", {"useForScreening": True})
    assert jev.enabled() is False


def test_enabled_true_with_key_and_toggle(data_dir):
    secretstore.set_connection("jev", {"apiKey": "jev_secret", "useForScreening": True})
    assert jev.enabled() is True


def test_enabled_falls_back_to_env_key(data_dir, monkeypatch):
    monkeypatch.setenv("JEV_API_KEY", "env_secret")
    secretstore.set_connection("jev", {"useForScreening": True})
    assert jev.enabled() is True


# --- question construction ----------------------------------------------


def test_one_request_covers_every_set_requirement(data_dir, monkeypatch, full_profile):
    secretstore.set_connection("jev", {"apiKey": "jev_secret", "useForScreening": True})
    captured = {}

    def handler(request):
        body = json.loads(request.data)
        captured["body"] = body
        captured["auth"] = request.headers.get("Authorization")
        return {"answers": {name: {"noul": 0.0} for name in body["questions"]}}

    _install_fake_urlopen(monkeypatch, handler)
    jev.evaluate_hard_requirements(full_profile, "some posting text")

    body = captured["body"]
    assert body["state"] == "some posting text"
    assert body["model"] == "jev-latest"
    assert captured["auth"] == "Bearer jev_secret"
    names = set(body["questions"])
    assert "rejected_role_type:internship" in names
    assert "salary_floor" in names
    assert "employment_country" in names
    assert "eor_allowed" in names
    assert "remote_model" in names
    for q in body["questions"].values():
        assert q["type"] == "noul"
        assert isinstance(q["instructions"], str) and q["instructions"]


def test_no_applicable_requirements_makes_no_request(data_dir, monkeypatch):
    secretstore.set_connection("jev", {"apiKey": "jev_secret", "useForScreening": True})

    def handler(request):
        raise AssertionError("should not be called")

    _install_fake_urlopen(monkeypatch, handler)
    profile = JobProfile(name="p", enabled=True, keywords=["backend"])
    assert jev.evaluate_hard_requirements(profile, "text") == []


def test_disabled_makes_no_request(data_dir, monkeypatch, full_profile):
    def handler(request):
        raise AssertionError("should not be called")

    _install_fake_urlopen(monkeypatch, handler)
    assert jev.evaluate_hard_requirements(full_profile, "text") == []


# --- threshold mapping ----------------------------------------------------


def test_answers_above_threshold_map_to_failures_below_to_passes(data_dir, monkeypatch):
    secretstore.set_connection("jev", {"apiKey": "jev_secret", "useForScreening": True})
    profile = JobProfile(name="p", enabled=True, keywords=["x"], eor_allowed=False, salary_floor=50000)

    def handler(request):
        body = json.loads(request.data)
        answers = {}
        for name in body["questions"]:
            answers[name] = {"noul": 0.8 if name == "eor_allowed" else 0.5}
        return {"answers": answers}

    _install_fake_urlopen(monkeypatch, handler)
    failures = jev.evaluate_hard_requirements(profile, "text")
    names = {name for name, _ in failures}
    assert names == {"eor_allowed"}


# --- fail-open --------------------------------------------------------------


def test_fail_open_on_timeout(data_dir, monkeypatch):
    secretstore.set_connection("jev", {"apiKey": "jev_secret", "useForScreening": True})
    profile = JobProfile(name="p", enabled=True, keywords=["x"], eor_allowed=False)

    def handler(request):
        return TimeoutError("timed out")

    _install_fake_urlopen(monkeypatch, handler)
    assert jev.evaluate_hard_requirements(profile, "text") == []


def test_fail_open_on_http_500(data_dir, monkeypatch, caplog):
    secretstore.set_connection("jev", {"apiKey": "jev_secret", "useForScreening": True})
    profile = JobProfile(name="p", enabled=True, keywords=["x"], eor_allowed=False)

    def handler(request):
        return urllib.error.HTTPError(jev.API_URL, 500, "Server Error", {}, None)

    _install_fake_urlopen(monkeypatch, handler)
    assert jev.evaluate_hard_requirements(profile, "text") == []
    assert "jev_secret" not in caplog.text


def test_check_key_ok(data_dir, monkeypatch):
    def handler(request):
        return {"answers": {"ping": {"noul": 0.1}}}

    _install_fake_urlopen(monkeypatch, handler)
    ok, detail = jev.check_key("a_key")
    assert ok is True


def test_check_key_no_key():
    ok, detail = jev.check_key("")
    assert ok is False


def test_check_key_fail_open_on_error(monkeypatch):
    def handler(request):
        return urllib.error.URLError("boom")

    _install_fake_urlopen(monkeypatch, handler)
    ok, detail = jev.check_key("a_key")
    assert ok is False


# --- non-dict / malformed responses ----------------------------------------


def test_fail_open_when_response_body_is_not_a_dict(data_dir, monkeypatch):
    secretstore.set_connection("jev", {"apiKey": "jev_secret", "useForScreening": True})
    profile = JobProfile(name="p", enabled=True, keywords=["x"], eor_allowed=False)

    def handler(request):
        return []

    _install_fake_urlopen(monkeypatch, handler)
    assert jev.evaluate_hard_requirements(profile, "text") == []


def test_check_key_fail_open_when_response_body_is_not_a_dict(monkeypatch):
    def handler(request):
        return []

    _install_fake_urlopen(monkeypatch, handler)
    ok, detail = jev.check_key("a_key")
    assert ok is False


def test_fail_open_on_incomplete_read(data_dir, monkeypatch):
    secretstore.set_connection("jev", {"apiKey": "jev_secret", "useForScreening": True})
    profile = JobProfile(name="p", enabled=True, keywords=["x"], eor_allowed=False)

    def handler(request):
        return ({}, http.client.IncompleteRead(b"x"))

    _install_fake_urlopen(monkeypatch, handler)
    assert jev.evaluate_hard_requirements(profile, "text") == []
