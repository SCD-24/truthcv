"""Recover the ``company`` and ``verdict`` of screening records that lost them.

Between the MCP tool surface gaining a ``role`` requirement and gaining a
``company``/``verdict`` one, ``record_screening`` advertised neither field in
its inputSchema — they reached the store only through ``**kwargs``. A model
that passed them from the RUNBOOK's instructions produced complete records; one
that went by the schema alone produced records with both fields blank. Those
records never entered the operator's approval queue, because
``screening.store.create`` routes on the verdict.

The agent that hit this worked around it by writing the verdict into
``posting_text`` as a leading ``[COMPANY: … | VERDICT: … ]`` block. This
one-off maintenance script parses that block back into the real fields.

For each stored screening whose ``company`` or ``verdict`` is blank:

* If the block is present and yields a company that passes
  ``validate_company_name`` and a verdict that passes ``validate_verdict``, the
  record is RECOVERABLE and -- under ``--apply`` -- rewritten through
  ``screening.store.update``. ``failing_criterion`` and ``reason`` are carried
  across too when the block names them and the stored field is empty.
* Otherwise it is MANUAL-REPAIR and is **never** rewritten: the operator needs
  to see what the agent actually recorded.

``posting_text`` keeps its block unless ``--strip-blocks`` is passed. That pass
removes the leading ``[...]`` prefix so the stored text is the posting again --
the operator drafts a letter from it verbatim, and several of these boards can
no longer be re-fetched, so it only strips where nothing can be lost: the record
must already carry a company and verdict, the block must close with a ``]`` that
has no further ``[`` before it, and the remaining text must be non-empty. Any
record failing one of those is reported and left alone.

Records that already carry both fields are left alone, which makes this script
**idempotent**: a second ``--apply`` recovers nothing. The default is a dry run
that writes nothing and only reports.

This script goes through ``screening.store`` for every read and write; it never
touches ``data/screenings.json`` directly.

**Stop the agent before running with ``--apply``.** This makes one write per
recovered record and another per stripped block, against the same file an agent
run records screenings into. The stores take a lock, so nothing is corrupted
either way, but a long repair interleaved with a run is needless contention:

    docker compose stop agent
    python scripts/repair_screening_verdicts.py --apply --strip-blocks
    docker compose start agent

Usage::

    python scripts/repair_screening_verdicts.py           # dry run, report only
    python scripts/repair_screening_verdicts.py --apply    # write the fixes
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

# Run as ``python scripts/repair_screening_verdicts.py`` and Python puts
# scripts/ on the path rather than the repo root, so the packages below would
# not resolve. Add the root explicitly rather than constrain how it is invoked.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import screening.store as screening_store  # noqa: E402
from agentconfig.store import load as agent_config_load  # noqa: E402
from screening.company import validate_company_name  # noqa: E402
from screening.model import validate_verdict  # noqa: E402

# The workaround block the agent wrote, e.g.
#   [COMPANY: Bjak | VERDICT: rejected | MATCHED PROFILE: … ]
#
# Every pattern below is applied to the BLOCK only, never to the whole
# posting_text (see `_block`). Searching the whole text let the posting's own
# prose supply the values: a body containing "Reason: we grew 3x last year"
# became the rejection reason. Each value also stops at a newline, because the
# fields are one-per-segment on a single line — without that, a block using a
# separator other than "|" swallowed the rest of itself into the company name.
# The body may not span lines: the agent wrote the block as a single line, and
# allowing newlines let an UNTERMINATED block run on until a "]" in the posting
# body (a "1] Python" list marker), whose text then got stripped as if it were
# part of the block.
_BLOCK_RE = re.compile(r"^\s*\[\s*COMPANY:(?P<body>[^\]\n]*)\]", re.IGNORECASE)
# A value runs to the next "|" or the end of the line. A block that used some
# other separator therefore captures the following fields too — which is
# detected and REFUSED below rather than guessed at: trimming at the next
# ALL-CAPS label looked tidy but silently truncated "Acme GmbH VERDICT: …" to
# "Acme Gmb", and a wrong employer name is worse than an unrepaired record.
_COMPANY_RE = re.compile(r"^\s*COMPANY:\s*(?P<value>[^|\n]+)", re.IGNORECASE)
# An ALL-CAPS "LABEL:" surviving inside a captured value means the block was
# not "|"-separated and the capture ran past its field.
_STRAY_LABEL_RE = re.compile(r"[A-Z][A-Z ]{2,}:")
_VERDICT_RE = re.compile(r"\bVERDICT:\s*(?P<value>[A-Za-z]+)", re.IGNORECASE)
# Singular and plural both occur; so does a trailing "ADDITIONALLY:" clause.
_CRITERION_RE = re.compile(r"\bFAILING CRITERI(?:ON|A):\s*(?P<value>[^|\n]+)", re.IGNORECASE)
_REASON_RE = re.compile(r"\bREASON:\s*(?P<value>[^|\n]+)", re.IGNORECASE)


def _block(posting_text: str) -> str | None:
    """The leading ``[COMPANY: … ]`` block's inner text, or None.

    Requires the block to open the text and to CLOSE with a ``]`` before any
    further ``[``. An unterminated block returns None rather than running to
    the first ``]`` anywhere in the document — that behaviour truncated real
    posting bodies whose first ``]`` was a list marker ("1] Python").
    """
    if not isinstance(posting_text, str):
        return None
    found = _BLOCK_RE.match(posting_text)
    if found is None or "[" in found.group("body"):
        return None
    return "COMPANY:" + found.group("body")


def _match(pattern: re.Pattern, text: str) -> str:
    """The pattern's stripped ``value`` group in ``text``, or ""."""
    found = pattern.search(text or "")
    return found.group("value").strip() if found else ""


def needs_repair(screening) -> bool:
    """Whether this record is missing a company or a verdict."""
    return not (screening.company or "").strip() or not (screening.verdict or "").strip()


def recover(screening) -> dict:
    """The fields recoverable from this record's posting_text block.

    Returns a patch dict for ``screening.store.update``, or an empty dict when
    the block yields no usable company/verdict pair. Only blank fields are
    filled: a value the record already holds always wins over the block.
    """
    block = _block(screening.posting_text or "")
    if block is None:
        return {}
    raw_company = _match(_COMPANY_RE, block)
    if _STRAY_LABEL_RE.search(raw_company):
        # Ambiguous block: report it as manual-repair rather than storing a
        # company name that is really three fields concatenated.
        return {}
    try:
        company = validate_company_name(raw_company)
        verdict = validate_verdict(_match(_VERDICT_RE, block))
    except ValueError:
        return {}

    patch = {}
    if not (screening.company or "").strip():
        patch["company"] = company
    if not (screening.verdict or "").strip():
        patch["verdict"] = verdict
    if not (screening.failing_criterion or "").strip():
        criterion = _match(_CRITERION_RE, block)
        if criterion:
            patch["failing_criterion"] = criterion
    if not (screening.reason or "").strip():
        reason = _match(_REASON_RE, block)
        if reason:
            patch["reason"] = reason
    return patch


def classify(screenings: list) -> tuple[list, list, list]:
    """Bucket screenings into (complete, recoverable, manual-repair).

    ``recoverable`` holds ``(screening, patch)`` pairs; ``manual`` holds the
    records that need a company or verdict but whose posting_text carries no
    usable block.
    """
    complete, recoverable, manual = [], [], []
    for s in screenings:
        if not needs_repair(s):
            complete.append(s)
            continue
        patch = recover(s)
        if patch:
            recoverable.append((s, patch))
        else:
            manual.append(s)
    return complete, recoverable, manual


def queues_for_approval(verdict: str) -> bool:
    """Whether ``store.create`` would have queued this verdict for the operator.

    Mirrors the rule in ``screening.store.create`` deliberately: ``update`` does
    not run it, so a record whose verdict is only being recovered now would keep
    an empty approval and stay invisible — which is the exact failure this
    script exists to undo.
    """
    if verdict == "deferred":
        return True
    return verdict == "passed" and agent_config_load().mode == "semi"


def apply_fixes(recoverable: list) -> list:
    """Write each recovered patch, queueing the ones that should be queued.

    Returns the records newly placed in the approval queue. An approval the
    operator has already decided is never overwritten: only a blank one is set.
    """
    queued = []
    for s, patch in recoverable:
        screening_store.update(s.id, patch)
        verdict = patch.get("verdict", s.verdict)
        if not (s.approval or "").strip() and queues_for_approval(verdict):
            screening_store.set_approval(s.id, "pending")
            queued.append(s)
    return queued


def print_report(complete: list, recoverable: list, manual: list, applied: bool) -> None:
    """Print the three counts, one line per repaired and per unfixable record."""
    print("dry run (nothing written)" if not applied else "applied changes")
    print(f"already-complete: {len(complete)}")
    print(f"recovered: {len(recoverable)}")
    for s, patch in recoverable:
        print(f"  {s.id} | {patch.get('company', s.company)} | {patch.get('verdict', s.verdict)} | {s.role}")
    print(f"needs-manual-repair: {len(manual)}")
    for s in manual:
        print(f"  {s.id} | {s.url} | {s.role}")
    if manual:
        print("Those carry no recoverable block; fix them on the Screenings page.")
    would = "queued for approval" if applied else "would be queued for approval"
    # Report against the patch, not the loaded record: on a dry run nothing has
    # been written, so `s.company` is still the blank this script is repairing.
    pending = [
        (s, patch)
        for s, patch in recoverable
        if not (s.approval or "").strip()
        and queues_for_approval(patch.get("verdict", s.verdict))
    ]
    print(f"{would}: {len(pending)}")
    for s, patch in pending:
        print(f"  {s.id} | {patch.get('company', s.company)} | {s.role}")


def strippable(screening) -> str | None:
    """The posting text with its leading ``[...]`` block removed, or None.

    Returns None -- meaning "do not touch this record" -- unless every
    condition holds: the record already carries the company and verdict the
    block encoded (so removing it discards nothing), the text opens with the
    block, the block closes with a ``]`` that no further ``[`` precedes (so the
    extent is unambiguous), and something remains after it.
    """
    if needs_repair(screening):
        return None
    text = (screening.posting_text or "").lstrip()
    block = _block(text)
    if block is None:
        return None
    # The block must re-parse to the company and verdict this record already
    # holds. That is what proves the "]" found is the block's own terminator
    # and not one inside a value: "[COMPANY: Acme (formerly Foo] Ltd) | …]"
    # otherwise strips to "Ltd) | VERDICT: rejected]" plus the real body,
    # keeping the debris and discarding nothing useful — but on other inputs
    # the same slip discards the posting itself.
    raw_company = _match(_COMPANY_RE, block)
    if _STRAY_LABEL_RE.search(raw_company):
        return None
    try:
        company = validate_company_name(raw_company)
        verdict = validate_verdict(_match(_VERDICT_RE, block))
    except ValueError:
        return None
    if company != (screening.company or "").strip():
        return None
    if verdict != (screening.verdict or "").strip().casefold():
        return None
    rest = text[text.index("]") + 1 :].strip()
    return rest or None


def strip_blocks(screenings: list, applied: bool) -> tuple[list, list]:
    """Strip the workaround block from every record where it is safe.

    Returns ``(stripped, skipped)``; ``skipped`` holds only records that still
    carry a block but did not meet every condition in ``strippable``.
    """
    stripped, skipped = [], []
    for s in screenings:
        if not (s.posting_text or "").lstrip().startswith("[COMPANY:"):
            continue
        rest = strippable(s)
        if rest is None:
            skipped.append(s)
            continue
        if applied:
            screening_store.update(s.id, {"posting_text": rest})
        stripped.append(s)
    return stripped, skipped


def print_strip_report(stripped: list, skipped: list, applied: bool) -> None:
    """Print what the block-stripping pass did or would do."""
    verb = "stripped" if applied else "would strip"
    print(f"{verb} posting_text blocks: {len(stripped)}")
    print(f"left alone (unsafe to strip): {len(skipped)}")
    for s in skipped:
        print(f"  {s.id} | {s.company or '(no company)'} | {s.role}")


def _parse_args(argv: list | None) -> argparse.Namespace:
    """Parse the CLI: one ``--apply`` flag, defaulting to a dry run."""
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--apply",
        action="store_true",
        help="write recovered fields; default is a dry run that writes nothing",
    )
    parser.add_argument(
        "--strip-blocks",
        action="store_true",
        help="also remove the leading [COMPANY: ...] block from posting_text",
    )
    return parser.parse_args(argv)


def main(argv: list | None = None) -> int:
    """Load screenings, classify, optionally apply fixes, and print the report."""
    args = _parse_args(argv)
    complete, recoverable, manual = classify(screening_store.load_all())
    if args.apply:
        apply_fixes(recoverable)
    print_report(complete, recoverable, manual, args.apply)
    if args.strip_blocks:
        # Re-read: the recovery pass above just wrote company/verdict, and
        # strippable() refuses to touch a record that still lacks them.
        stripped, skipped = strip_blocks(screening_store.load_all(), args.apply)
        print_strip_report(stripped, skipped, args.apply)
    return 0


if __name__ == "__main__":
    sys.exit(main())
