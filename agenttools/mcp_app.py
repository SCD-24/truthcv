"""The agent tool registry and the JSON Schemas advertised for it.

This module owns *what* the tools are; the MCP streamable-HTTP JSON-RPC
endpoint that serves them is built and registered in ``api/main.py``.
"""

from __future__ import annotations

import inspect
from typing import Any

from agenttools.tools_boards import record_company_board as _record_company_board
from agenttools.tools_ledger import (
    check_cooldown as _check_cooldown,
    get_approved_applications as _get_approved_applications,
    get_canonical_cv as _get_canonical_cv,
    get_job_profiles as _get_job_profiles,
    get_profile_answers as _get_profile_answers,
    recommend_salary as _recommend_salary,
    report_apply_failure as _report_apply_failure,
    record_application as _record_application,
    record_screening as _record_screening,
)
from agenttools.tools_letter import generate_cover_letter as _generate_cover_letter
from agenttools.tools_research import (
    get_company_findings as _get_company_findings,
    record_company_finding as _record_company_finding,
)
from agenttools.tools_runs import (
    finish_run as _finish_run,
    record_run_note as _record_run_note,
    start_run as _start_run,
)


_TOOL_REGISTRY = {
    "generate_cover_letter": (
        _generate_cover_letter,
        "Generates a guardrailed, per-role cover letter.",
    ),
    "record_application": (
        _record_application,
        "Records a submitted application and its evidence trail. Pass company and role, or a screening_id to inherit them from the approved queue item.",
    ),
    "record_screening": (
        _record_screening,
        "Records one screening verdict. company, role and url are ALL required and the call is rejected, storing nothing, without a usable value for each: "
        "company is the employing entity (never a placeholder like \"Unknown\"), role is the job title as posted, url is the posting's own URL. "
        "verdict is required and must be exactly rejected, passed or deferred — UNLESS the posting could not be read at all (403, login wall, dead link, expired listing), "
        "in which case leave verdict empty and pass screening_blocker instead, set to one of: login_required, unreadable, not_found, expired. "
        "Never guess a verdict for a posting you could not read — that fabricates an evaluation that never happened. "
        "You must also pass posting_text — the posting exactly as you read it — because the operator will draft the cover letter from it days later, on a page the agent never sees.",
    ),
    "check_cooldown": (
        _check_cooldown,
        "Checks whether a company/role is in cooldown.",
    ),
    "get_canonical_cv": (
        _get_canonical_cv,
        "Returns the stored canonical CV asset to attach.",
    ),
    "get_profile_answers": (
        _get_profile_answers,
        "Returns the operator's canonical screening answers from the answers store. Never assume or hard-code any of these — always call this tool. "
        "Pass company — the employing entity for the application currently being filled in — so the returned email is the per-company tracking address for that employer. "
        "Type the returned email verbatim; never construct, edit, or 'correct' an address yourself. "
        "Omitting company returns the plain address, which is correct only when no specific application is being filled in.",
    ),
    "get_job_profiles": (
        _get_job_profiles,
        "Returns the configured job search profiles and their full criteria (salary band, remote model, employment country, and the rest).",
    ),
    "recommend_salary": (
        _recommend_salary,
        "Given the matched profile's name (and optionally a derived proposed figure), returns the operator's salary ask for that profile, clamped to its configured band.",
    ),
    "get_approved_applications": (
        _get_approved_applications,
        "Returns the postings the operator approved for this run to apply to. Pass your run_id "
        "(from start_run) so the list is capped for this run and every returned item is claimed "
        "by it — a shorter list than you expected means the per-run cap was reached, not that "
        "work was lost; call it again on a later run for the rest. "
        "An entry with a non-empty blocked_reason must NOT be applied to — report it instead, "
        "and it never counts against the cap.",
    ),
    "report_apply_failure": (
        _report_apply_failure,
        "Records why an approved application could not be completed. The item "
        "stays queued for the next run. When the form sat behind a sign-in or "
        "registration wall, also pass blocker='login_required' and signin_url "
        "(the login page URL) — that is what tells the operator which site to "
        "sign in to. Never create an account yourself.",
    ),
    "record_company_board": (
        _record_company_board,
        "Records a target company's careers URL and ATS once verified on the employer's own site.",
    ),
    "record_company_finding": (
        _record_company_finding,
        "Records one sourced, dated company research finding (e.g. employment entity, employer rating). "
        "Every field is required except as_of and note. source_url must be the page the claim was actually "
        "read from — a company-level claim must be traceable. source_class is one of the ranked classes, "
        "strongest first: audited_accounts, regulatory_filing, listed_bond_price, company_statement, press, "
        "review_site, unattributed — pick the strongest source actually available, not the first one found. "
        "as_of is the date the SOURCE is dated and must be left empty when the source carries no date — "
        "never inferred, never today's date.",
    ),
    "get_company_findings": (
        _get_company_findings,
        "Returns every finding recorded for a company and its open contradictions. A non-empty "
        "open_contradictions means the company must NOT be applied to until the operator resolves it.",
    ),
    "start_run": (
        _start_run,
        "Call this ONCE, at the very start of a run, with the run_id given in your prompt. "
        "Keep passing that same run_id on every subsequent tool call that accepts one. "
        "Safe to call again with the same run_id if you are unsure whether you already did — "
        "it will not reset your coverage counters.",
    ),
    "finish_run": (
        _finish_run,
        "Call this before exiting — including when you are stopping EARLY, not only on a normal "
        "finish. Pass an honest stopped_reason describing where you stopped (e.g. 'apply cap "
        "reached', 'browser session died', 'no more postings found'). A run that ends without "
        "calling this is indistinguishable from one that crashed.",
    ),
    "record_run_note": (
        _record_run_note,
        "Leaves a free-text note on the run record for context that does not fit the coverage "
        "counters (postings seen, screenings recorded, applications submitted, etc).",
    ),
}


_JSON_TYPES: dict[Any, str] = {
    str: "string",
    int: "integer",
    float: "number",
    bool: "boolean",
    list: "array",
    dict: "object",
}


def _json_type(annotation: Any) -> str:
    """Best-effort JSON Schema type for a parameter annotation.

    Annotations here are evaluated lazily (``from __future__ import
    annotations``), so they arrive as strings. Unions and anything unrecognised
    fall back to "string", which keeps the tool callable rather than
    advertising a type the caller cannot satisfy.
    """
    if not isinstance(annotation, str):
        return _JSON_TYPES.get(annotation, "string")
    text = annotation.split("|")[0].strip().lower()
    for py_type, json_type in _JSON_TYPES.items():
        if text.startswith(py_type.__name__):
            return json_type
    return "string"


# Parameters that exist for the process, not the caller. `provider` is
# generate_cover_letter's dependency-injection seam for tests; advertising it
# would invite the agent to pass one. Excluded from every tool's schema.
_INTERNAL_PARAMS = frozenset({"provider"})


def _input_schema(fn: Any) -> dict:
    """Derive a tool's inputSchema from its signature.

    Without this every tool advertised an empty property set, so a caller
    reading the schema had no way to know that seven of the nine take
    arguments — it would call them bare and get a TypeError back. Parameters
    with no default are required; a ``**kwargs`` tool accepts any field.
    """
    properties: dict[str, dict] = {}
    required: list[str] = []
    additional = False
    for name, param in inspect.signature(fn).parameters.items():
        if param.kind is inspect.Parameter.VAR_KEYWORD:
            additional = True
            continue
        if param.kind is inspect.Parameter.VAR_POSITIONAL:
            continue
        if name in _INTERNAL_PARAMS:
            continue
        properties[name] = {"type": _json_type(param.annotation)}
        if param.default is inspect.Parameter.empty:
            required.append(name)
    schema: dict[str, Any] = {
        "type": "object",
        "properties": properties,
        "required": required,
    }
    if additional:
        schema["additionalProperties"] = True
    return schema
