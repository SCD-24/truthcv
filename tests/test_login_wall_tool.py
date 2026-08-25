"""report_apply_failure carries the structured login-wall blocker through to the store."""

from __future__ import annotations

from agenttools.tools_ledger import report_apply_failure
from agenttools.mcp_app import _TOOL_REGISTRY
from screening import store


def test_reports_a_login_wall_with_its_url(data_dir):
    s = store.create({"company": "Acme", "role": "Dev", "verdict": "passed"})
    result = report_apply_failure(
        s.id,
        "sign-in required",
        blocker="login_required",
        signin_url="https://acme.wd3.myworkdayjobs.com/login",
    )
    assert result == {"ok": True, "attempts": 1}
    stored = store.get(s.id)
    assert stored.apply_blocker == "login_required"
    assert stored.signin_url == "https://acme.wd3.myworkdayjobs.com/login"


def test_plain_failure_still_works(data_dir):
    s = store.create({"company": "Acme", "role": "Dev", "verdict": "passed"})
    result = report_apply_failure(s.id, "form timed out")
    assert result["ok"] is True
    assert store.get(s.id).apply_blocker == ""


def test_unknown_id_is_still_reported_cleanly(data_dir):
    result = report_apply_failure("nope", "x", blocker="login_required")
    assert result == {"ok": False, "reason": "unknown screening id"}


def test_tool_description_tells_the_agent_about_login_walls():
    _fn, description = _TOOL_REGISTRY["report_apply_failure"]
    assert "login_required" in description
