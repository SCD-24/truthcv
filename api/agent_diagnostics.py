"""Bounded GET-only reader for the agent control server's metadata endpoints.

The operational agent proxy is deliberately separate: this client has no
write method, no caller-supplied URL, and never forwards upstream bodies or
exception messages to the remote diagnostics MCP client.
"""

from __future__ import annotations

import asyncio
import json
import os
import re
import socket
import urllib.error
import urllib.request
from datetime import datetime, timezone
from urllib.parse import urlencode

import runs.store as _runs_store

_TIMEOUT_SECONDS = 5
_MAX_RESPONSE_BYTES = 256 * 1024
_MAX_EVENTS = 200
_SAFE_ID = re.compile(r"[a-zA-Z0-9_-]{1,80}\Z")
_SAFE_TOOL = re.compile(r"[a-zA-Z0-9_]{1,80}\Z")
_PHASES = {"registry_refresh", "compaction", "model", "tool", "backoff"}
_STATUSES = {"start", "success", "error"}
_EVENT_KEYS = {"schema_version", "run_id", "sequence", "at", "operation_id", "phase", "status",
               "duration_ms", "tool_name", "turn", "retry_attempt", "delay_ms", "active_operations",
               "active_truncated", "truncated"}
_ACTIVE_KEYS = {"operation_id", "phase", "started_at", "tool_name", "turn"}
_STATUS_FIELDS = {"running": False, "cancelling": False, "lastStartedAt": None,
                  "lastFinishedAt": None, "lastExitCode": None, "lastCancelled": False,
                  "currentRunId": None, "lastRunId": None, "scheduleEnabled": None}


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def _integer(value, minimum=0) -> bool:
    return type(value) is int and minimum <= value <= 9007199254740991


def _timestamp(value) -> bool:
    if not isinstance(value, str) or not re.fullmatch(r"\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d\.\d{3}Z", value):
        return False
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).isoformat(timespec="milliseconds").replace("+00:00", "Z") == value
    except ValueError:
        return False


def _safe_id(value) -> bool:
    return isinstance(value, str) and _SAFE_ID.fullmatch(value) is not None


def _active(op) -> bool:
    return (isinstance(op, dict) and op.keys() <= _ACTIVE_KEYS
            and _safe_id(op.get("operation_id")) and op.get("phase") in _PHASES
            and _timestamp(op.get("started_at"))
            and ("tool_name" not in op or (op["phase"] == "tool" and isinstance(op["tool_name"], str)
                                             and _SAFE_TOOL.fullmatch(op["tool_name"]) is not None))
            and ("turn" not in op or _integer(op["turn"])))


def _event(event, run_id: str) -> bool:
    if not isinstance(event, dict) or not event.keys() <= _EVENT_KEYS:
        return False
    active = event.get("active_operations")
    return (type(event.get("schema_version")) is int and event["schema_version"] == 1
            and event.get("run_id") == run_id and _integer(event.get("sequence"), 1)
            and _timestamp(event.get("at")) and _safe_id(event.get("operation_id"))
            and event.get("phase") in _PHASES and event.get("status") in _STATUSES
            and type(event.get("active_truncated")) is bool and type(event.get("truncated")) is bool
            and isinstance(active, list) and len(active) <= 128 and all(_active(op) for op in active)
            and ("tool_name" not in event or (event["phase"] == "tool" and isinstance(event["tool_name"], str)
                                               and _SAFE_TOOL.fullmatch(event["tool_name"]) is not None))
            and ("duration_ms" not in event or (event["status"] != "start" and _integer(event["duration_ms"])))
            and all(key not in event or _integer(event[key]) for key in ("turn", "retry_attempt", "delay_ms")))


def _status(data) -> dict | None:
    if not isinstance(data, dict) or type(data.get("running")) is not bool:
        return None
    result = {key: data.get(key, default) for key, default in _STATUS_FIELDS.items()}
    if (any(type(result[key]) is not bool for key in ("running", "cancelling", "lastCancelled"))
            or result["scheduleEnabled"] is not None and type(result["scheduleEnabled"]) is not bool
            or any(result[key] is not None and not _timestamp(result[key]) for key in ("lastStartedAt", "lastFinishedAt"))
            or result["lastExitCode"] is not None and not _integer(result["lastExitCode"])
            or any(result[key] is not None and not _safe_id(result[key]) for key in ("currentRunId", "lastRunId"))):
        return None
    return result


def _events(data, run_id: str, limit: int, before: int | None) -> bool:
    if not isinstance(data, dict) or set(data) != {"schema_version", "run_id", "availability", "reason", "events",
                                               "next_before_sequence", "truncated", "last_activity_at",
                                               "active_operations", "active_truncated", "observed_at", "running", "currentRunId"}:
        return False
    page = data["events"]
    active = data["active_operations"]
    next_seq = data["next_before_sequence"]
    if (type(data["schema_version"]) is not int or data["schema_version"] != 1 or data["run_id"] != run_id
            or data["availability"] not in ("available", "unavailable")
            or data["reason"] not in (None, "missing", "malformed", "unreadable", "telemetry_unavailable")
            or type(data["truncated"]) is not bool or type(data["active_truncated"]) is not bool
            or type(data["running"]) is not bool
            or not _timestamp(data["observed_at"]) or not isinstance(page, list) or len(page) > limit
            or not isinstance(active, list) or len(active) > 128 or not all(_active(op) for op in active)
            or data["currentRunId"] is not None and not _safe_id(data["currentRunId"])
            or next_seq is not None and not _integer(next_seq, 1)
            or data["last_activity_at"] is not None and not _timestamp(data["last_activity_at"])):
        return False
    if data["availability"] == "unavailable":
        return (data["reason"] is not None and not page and not active and next_seq is None
                and data["last_activity_at"] is None and data["truncated"] is False
                and data["active_truncated"] is False)
    if data["reason"] is not None or not all(_event(item, run_id) for item in page):
        return False
    sequences = [item["sequence"] for item in page]
    return (sequences == sorted(set(sequences)) and (not sequences or before is None or sequences[-1] < before)
            and (next_seq is None or bool(sequences) and next_seq == sequences[0])
            and data["last_activity_at"] is not None
            and (data["running"] and data["currentRunId"] == run_id
                 or not active and data["active_truncated"] is False))


def _fetch(path: str) -> tuple[dict | None, str | None, str]:
    token = os.environ.get("AGENT_API_TOKEN", "").strip()
    if not token:
        return None, "missing_token", "unknown"
    port = os.environ.get("AGENT_CONTROL_PORT", "9099")
    if not port.isdecimal() or not 1 <= int(port) <= 65535:
        return None, "malformed_response", "unknown"
    req = urllib.request.Request(f"http://agent:{port}{path}", method="GET", headers={"X-Agent-Token": token})
    try:
        with urllib.request.build_opener(_NoRedirect()).open(req, timeout=_TIMEOUT_SECONDS) as resp:
            body = resp.read(_MAX_RESPONSE_BYTES + 1)
        if len(body) > _MAX_RESPONSE_BYTES:
            return None, "malformed_response", "reachable"
        data = json.loads(body)
        return data, None, "reachable"
    except urllib.error.HTTPError as exc:
        if exc.code in (401, 403):
            return None, "token_mismatch", "reachable"
        if exc.code == 404:
            return None, "old_endpoint", "reachable"
        return None, "upstream_error", "reachable"
    except (TimeoutError, socket.timeout):
        return None, "timeout", "unreachable"
    except urllib.error.URLError as exc:
        if isinstance(exc.reason, (TimeoutError, socket.timeout)):
            return None, "timeout", "unreachable"
        return None, "unreachable", "unreachable"
    except OSError:
        return None, "unreachable", "unreachable"
    except (ValueError, UnicodeError, TypeError):
        return None, "malformed_response", "reachable"


async def get_agent_status() -> dict:
    """Report only trusted supervisor state; a failed probe has unknown ownership."""
    data, reason, reachability = await asyncio.to_thread(_fetch, "/status")
    try:
        status = _status(data) if reason is None else None
    except (TypeError, ValueError):
        status = None
    if reason is None and status is None:
        reason = "malformed_response"
    return {"observed_at": _now(), "reachability": reachability,
            "availability": "available" if reason is None else "unavailable", "reason": reason,
            **(status or {})}


async def get_run_events(run_id: str, limit: int = 50, before_sequence: int | None = None) -> dict:
    """Read a validated page for a retained run; never interpret raw run logs."""
    base = {"schema_version": 1, "run_id": run_id if _safe_id(run_id) else None,
            "observed_at": _now(), "reachability": "unknown", "ownership": "unknown"}

    def unavailable(reason: str, reachability: str = "unknown", supervisor: dict | None = None) -> dict:
        ownership = ("active" if supervisor["running"] and supervisor["currentRunId"] == run_id
                     else "inactive") if supervisor is not None else "unknown"
        return {**base, "availability": "unavailable", "reason": reason, "reachability": reachability,
                "ownership": ownership, "events": [], "next_before_sequence": None, "truncated": False,
                "last_activity_at": None, "active_operations": [], "active_truncated": False,
                **({"running": supervisor["running"], "currentRunId": supervisor["currentRunId"]}
                   if supervisor is not None else {})}

    if not _safe_id(run_id) or not _integer(limit, 1) or limit > _MAX_EVENTS or (
            before_sequence is not None and not _integer(before_sequence, 1)):
        return unavailable("invalid_request")
    if await asyncio.to_thread(_runs_store.get, run_id) is None:
        return unavailable("unknown_run")
    path = f"/diagnostics/runs/{run_id}/events?{urlencode({'limit': limit, **({'before_sequence': before_sequence} if before_sequence is not None else {})})}"
    data, reason, reachability = await asyncio.to_thread(_fetch, path)
    if reason is not None:
        return unavailable(reason, reachability)
    try:
        valid = _events(data, run_id, limit, before_sequence)
    except (TypeError, ValueError):
        valid = False
    if not valid:
        return unavailable("malformed_response", reachability)
    if data["availability"] == "unavailable":
        mapped = {"missing": "absent_telemetry", "telemetry_unavailable": "telemetry_unavailable"}
        return unavailable(mapped.get(data["reason"], "malformed_response"), reachability, data)
    ownership = "active" if data["running"] and data["currentRunId"] == run_id else "inactive"
    return {**data, "reachability": reachability, "ownership": ownership,
            "active_operations": data["active_operations"] if ownership == "active" else []}
