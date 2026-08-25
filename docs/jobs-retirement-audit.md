# Jobs repo retirement audit

Written for plan `retire-jobs-repo` (p-ed1ed29b), task t-1, in plan set
`jobs-into-truthcv`.

**Placeholders used below:** `<jobs-repo>` stands for the old Jobs repository's
working tree (its absolute path); `<truthcv>` stands for this repository's
working tree (its absolute path). Filenames that embedded the maintainer's
real name have been replaced with neutral filenames below; where more than one
generation or format of the same document existed, each keeps a distinct
neutral name so they stay distinguishable from one another.

Every entry in `<jobs-repo>` is classified below as one of:

- **migrated** — carried into TruthCV; the destination is named.
- **retired** — deliberately superseded; what supersedes it is named.
- **detritus** — working state with no lasting value.
- **BLOCKER** — fits none of the three. Per the task's own terms, a blocker stops
  the plan rather than being reasoned away.

The audit covers the **on-disk** tree, not the git-tracked tree. `applications/`
and `scratchpad/` are gitignored in the Jobs repo — its `.gitignore` says it
tracks "the tooling, scripts and docs — not the application artifacts", because
those artifacts carry a phone number and home address. They exist in exactly one
place: that working tree. Deleting it deletes them.

## Verdict

**Both blockers are now cleared.** They were real when this audit was written
and were fixed afterwards, in this plan; see *Blocker resolution* below for
what was actually done and how it was verified. The rest of the tree was
already fully accounted for.

**Task t-5 still must not run unattended.** It deletes the Jobs working tree,
which holds the only copy of gitignored personal data. Clearing the blockers
removed the reasons the deletion would have *lost* something; it does not
remove the need for the user to take a backup and say go.

---

## Blockers

### B1 — The plain-text application log, and the renderer that regenerates it

| Path | Status |
|---|---|
| `applications/APPLICATION_LOG.md` | 353 lines, gitignored, exists only on disk |
| `appreview/render.py` | the only implementation of the renderer |
| `bin/render-log` | its CLI entry point |
| `tests/test_render.py` | its test suite |

Decision **D4** of this plan set was explicit: `APPLICATION_LOG.md` survives, and
`render.py`'s renderer *and* its `RenderRefused` completeness guard are ported
into TruthCV, so that a plain-text log exists outside the application.

It was never ported. Searching the TruthCV build tree for `APPLICATION_LOG`,
`RenderRefused` and `render.py` returns nothing. Searching `.aether/planned-work.json`
— the whole 10-plan set — returns nothing for the same three terms.

So this is not a task that was completed badly. **No plan in the set ever carried
the work**, and the ruling was lost between the decision and the plan text.

The consequence is specific to t-5. The log file is gitignored in Jobs and has no
copy in TruthCV; the renderer that could regenerate it from records is likewise
only in Jobs. Deleting the Jobs tree therefore destroys the log *and* the ability
to rebuild it, in one step. The log's own header states it is generated from
`applications/records/*.json` — those records **are** migrated, so the content is
recoverable *if and only if* the renderer is ported first.

### B2 — Canonical answers and canonical CV exist only in a disposable worktree

| Path | Status |
|---|---|
| `data/answers.yaml` | present in the forest worktree only |
| `data/canonical_cv.pdf` | present in the forest worktree only |

`data/` is gitignored in TruthCV (`.gitignore` line 1). The live data volume is
`<truthcv>/data` — that is what `docker-compose.yml` mounts,
and it is where the history migration correctly wrote its 33 applications and 117
screening rows.

But the truth-store plan wrote `answers.yaml` and `canonical_cv.pdf` into the
*forest worktree's* `data/` instead. Those two files are therefore:

- absent from the live volume,
- not committable, because `data/` is gitignored, and so
- destroyed when the forest worktree is cleaned up after merge.

These back the `get_profile_answers` and `get_canonical_cv` MCP tools — the
canonical answers the agent types into ATS forms, and the CV it attaches. Losing
them silently disarms the agent.

This is not caused by the Jobs retirement, but it is a hard stop for **t-2**,
which requires "the canonical CV present as a profile asset" and treats any
shortfall as a hard stop. It is present in the wrong tree.

`canonical_cv.pdf` is byte-identical (md5 `f98a5097…`) to the current CV
export, registered in the Jobs tree as `cv_v2.pdf`, so its provenance is
confirmed and it is
reconstructible. `answers.yaml` is **not** reconstructible from the Jobs repo — it
was transcribed from the runbook during this plan set.

---

## Migrated

| Jobs path | TruthCV destination |
|---|---|
| `applications/records/*.json` (11 records) | `data/applications.json` — merged with the 22 pre-existing records, 33 total |
| `applications/SCREENING_LOG.md` | `data/screenings.json` — 87 rejected/deferred + 30 cooldowns = 117 rows |
| `applications/<Company>/cover_letter_*.{pdf,docx}`, `cv_*.{pdf,docx}` (17 dirs) | `data/` — verified present; every file matched by name except one, see Retired |
| `applications/runs/*.log` (6 files) | superseded by the `agent-runs` volume; historical logs are detritus, see below |
| `DAILY_APPLICATION_RUNBOOK.md` | `agent/RUNBOOK.md` |
| `docker/Dockerfile`, `entrypoint.sh`, `mcp.json` | `agent/Dockerfile`, `agent/entrypoint.sh`, `agent/mcp.json` |
| `bin/daily-apply.sh` | `agent/daily-apply.sh` |
| `docker/smoke-test.sh` | `agent/smoke-test.sh` |
| `docker/README.md` | `agent/README.md` |
| `appreview/schema.py` | `applications/model.py` — the evidence-trail fields were absorbed into the TruthCV record |
| `appreview/store.py` | `applications/store.py` |
| `cv_v2.pdf` (the current CV export) | `data/canonical_cv.pdf` (byte-identical) — **but see B2** |
| `tests/test_schema.py`, `test_store.py` | `tests/test_applications_model.py` and siblings |

## Retired

| Jobs path | Superseded by |
|---|---|
| `reviewer/app.py`, `reviewer/templates/*`, `reviewer/static/style.css`, `bin/reviewer` | Decision D3: the FastAPI/Jinja reviewer dies; its three screens were rebuilt as MUI/ledger surfaces in `web/` |
| `tests/test_app.py` | tests the retired reviewer |
| `appreview/backfill.py`, `bin/backfill-records`, `tests/test_backfill.py` | a one-time migration off `APPLICATION_LOG.md.prebackfill`, already spent |
| `applications/APPLICATION_LOG.md.prebackfill` | pre-backfill snapshot; the backfill it fed has run |
| `docker/render-pdf` | Decision: TruthCV's `renderer/` is the one surviving implementation; the WeasyPrint/LibreOffice path is dropped |
| `docker/compose.yaml` | `docker-compose.yml` in TruthCV, now carrying both services |
| `applications/<company>/coverletter_<company>.docx` (the maintainer's-name-prefixed original) | an older manually-named copy; record `245bccd01cae` points at `cover_letter_245bccd01cae.{pdf,docx}`, both present in TruthCV |
| `applications/*.docx`, `*.pdf` loose at top level (nine company-named files) | manual-era duplicates of files now stored by document id in `data/` |
| `applications/cv_pii_rm.docx` | a PII-stripped variant predating the truth store |
| `cv_v1.{docx,pdf}`, `cv_full_2026.pdf`, `cv_v2.{html,md}` | earlier CV generations (`cv_v1.*` predates `cv_v2.*`; `cv_full_2026.pdf` is a separately-named earlier export); `cv_v2.pdf` is the canonical one |
| `requirements.txt` | TruthCV's own dependency set |
| `applications/cv_harvard.txt`, `cv_mit.txt` | CV format references, superseded by the truth store's templates |
| `docs/superpowers/plans/`, `docs/superpowers/specs/` | design history for the retired reviewer |

## Detritus

`.git`, `.gitignore`, `.aether/`, `.superpowers/`, `.pytest_cache/`,
`.playwright-mcp/`, `DAILY_APPLICATION_RUNBOOK.md.bak`,
`applications/.directory`, `applications/agentic_ide.png`,
`applications/linkedin-cold-message.txt`, `applications/runs/*.log`,
`scratchpad/` (its `*_cover.pdf` / `*_cover_and_cv.pdf` outputs are already in
TruthCV's `data/` under `jobs_<id>_*` names).

## Not covered by this plan — handled by t-3

`remote-germany-targets.md` and `remote-germany-targets.ods` are the agent's
target-company queue and are referenced by the run prompt. t-3 brings them into
TruthCV as `agent/targets.md`.

## Note on `applications/applications.csv`

Not migrated, deliberately. It has 21 rows whose columns are exactly the
Application model and whose companies are exactly those already in TruthCV — it
is an export of the live ledger, not a separate population. Importing it would
have duplicated all 22 pre-existing records. Task t-4 of `migrate-jobs-history`
was cancelled for this reason.

## Blocker resolution

### B1 resolved — the log renderer is ported

`appreview/render.py`'s renderer and its `RenderRefused` completeness guard now
live in TruthCV as `applications/log_render.py`, driven by the tracker's own
`Application` dataclass rather than Jobs' record dicts. `scripts/render_application_log.py`
replaces `bin/render-log`.

Three deliberate departures from the original, each because the destination
differs from the source:

- **It renders every application, not only the agent-submitted ones.** The
  ledger is now one population of 33. Rendering the 11 agent-submitted records
  would have dropped 22 and reintroduced precisely the silent-omission failure
  the completeness guard exists to prevent.
- **It does not translate between status vocabularies.** Migrated records carry
  Jobs' `confirmed`/`pending`; records created in TruthCV carry `Applied`,
  `Rejected`, `Waiting`, `Draft`. Both render as themselves, and a record is
  only ever called *confirmed* when its own status says so. A rejected record
  that was nonetheless confirmed keeps its confirmation text on its own line, so
  no submission evidence is lost to the status having moved on.
- **It writes to `data/log/APPLICATION_LOG.md`, one directory below the volume
  root.** `GET /api/download/{name}` serves the data volume root by bare
  filename with no authentication, and the log carries the same personal data
  the records do. The route rejects any name containing a path separator, so a
  subdirectory is out of its reach. Same reasoning that put the migration
  backups in `data/migration/`.

  **Do not read that as a security control.** Review of this change established
  that it buys tidiness and nothing more, for two pre-existing reasons recorded
  under *Security posture* below. The log is where it is because that is the
  right place for it, not because being there protects it.

The file is written atomically (temp file, then rename) and then explicitly
`chmod`ed to 0644: `mkstemp` creates 0600 and `os.replace` preserves it, which
would have left a log written by the container as root unreadable to the human
it exists for.

Verified: 12 tests in `tests/test_log_render.py` and `tests/test_log_render_mode.py`
pass. The completeness guard was teeth-checked — stubbing it out makes exactly
the two refusal tests fail, and they pass again once it is restored. Rendered
against the live ledger, the log is 609 lines carrying 33 record markers, 33 of
them distinct.

### B2 resolved — and it was smaller than the audit claimed

This audit stated that `data/answers.yaml` was not reconstructible. **That was
wrong.** The file in the worktree held only empty strings plus a pointer to the
CV. The canonical answers are hard-coded as dataclass defaults on `Answers` in
`truth/answers.py`, which is version-controlled, and `load()` falls back to them
when the file is absent. Nothing was ever at risk of being lost.

**Superseded — the paragraph above is no longer true.** Those dataclass
defaults held the maintainer's real phone number, name, email, work
authorisation and salary in a version-controlled file, which is personal data
that should never have shipped as source. They have since been removed:
every field on `Answers` now defaults to `""`, and `load()` falls back to
blanks, not to real values, when `answers.yaml` is absent. "Nothing was ever
at risk of being lost" was an accurate description of the code as it stood
when that correction was written; it is **not** an accurate description of
the code today. The canonical answers now exist in exactly two places: the
gitignored `answers.local.yaml` (seeded from the tracked template
`answers.example.yaml` — see the repo root `README.md` and `agent/README.md`)
and whatever `data/answers.yaml` currently holds on the live data volume.
Neither is in version control, and there is no hard-coded fallback. This is
the state the original, uncorrected B2 blocker above already warned about —
`answers.yaml` is not reconstructible from source — and that original warning
is the one that now holds again.

What genuinely needed moving was the CV. It was copied out of the Jobs tree and
**registered on the live data volume as `data/canonical_cv.pdf`** (md5
`f98a5097…`, byte-identical to the Jobs copy), which is what `canonical_cv()`
resolves and what `GET /api/download/canonical_cv.pdf` serves. That registered
asset is the durable copy; deleting the Jobs tree loses nothing.

The CV is **not** version-controlled. It is personal data, so `assets/` is
gitignored and a fresh clone will not contain it — the data volume is its only
durable home. The copy under `assets/` in a working tree is a convenience, not
a source of truth, and is expected to disappear with the tree. `truth/answers.py` no longer refers to a path inside the Jobs repo:
`_JOBS_CANONICAL_CV` became `_LOCAL_CANONICAL_CV`, an un-versioned convenience
default for seeding from a working tree that happens to hold the export, and
`seed_canonical_cv_from_jobs` became `seed_canonical_cv`. Seeding elsewhere
takes an explicit path: `python -m truth.answers <path-to-cv.pdf>`.

Registration was done through a throwaway container mounting the same volume
(it is root-owned and not writable from the host), rather than by mutating the
running application.

**Residual gap, not created by this work:** `data/migration/jobs-archive/`
covers `applications/` and `scratchpad/` but not the three CV PDFs at the Jobs
tree root. `cv_v2.pdf` is safe (it is the registered asset), but
`cv_v1.pdf` and `cv_full_2026.pdf` — earlier generations,
superseded per the inventory above — exist only in the Jobs tree and would be
lost at t-5. The archive directory is root-owned, so they cannot be copied in
from the host; it needs the same throwaway-container route if you want them kept.

## t-2 — migration reconciliation

Measured against the live data volume, not inferred.

| Quantity | Count |
|---|---|
| Application records in the ledger | 33 |
| — carried in from Jobs (`capture_method` set) | 11 |
| — carrying `confirmation.text` | 10 |
| Screening records | 117 |
| — verdict `rejected` | 70 |
| — verdict `deferred` | 47 |
| — carrying a verbatim `cooldown_expires` | 30 |
| Record markers in the rendered log | 33 (33 distinct) |

The canonical CV is present as a profile asset: `canonical_cv_asset_id` is
`canonical_cv.pdf`, resolving to a real file on the volume. This was B2's
blocking condition and is now satisfied.

**Cooldowns still fire for companies that exist only in migrated history.**
The effective cooldown window is 90 days. Spot-checked:

| Company | In cooldown | Expires | Present before migration |
|---|---|---|---|
| *(migrated company A)* | yes | 2026-11-11 | no |
| *(migrated company B)* | yes | 2026-11-11 | no |
| *(migrated company C)* | yes | 2026-11-11 | no |
| *(migrated company D)* | yes | 2026-11-11 | no |
| *(a company never seen)* | no | — | — |

The control matters: an unknown company reports **not** in cooldown, so the
positives above are the screening history answering, not a check that says yes
to everything.

One honest caveat carried forward from the migration: the Jobs screening log's
own cooldown was roughly 30 days, while TruthCV's default is 90. The dates the
log recorded are stored verbatim, but the *effective* expiry reported here is
the longer one. The agent therefore over-blocks rather than under-blocks.

## The Jobs archive — what makes t-5 survivable

Most of what made deleting the Jobs tree frightening was never in its git
history at all. `applications/` and `scratchpad/` are gitignored there, so
cloning or restoring the repository would not bring them back; deleting the
working tree is the only deletion that matters.

A verbatim copy of everything irreplaceable now sits on the data volume at
`data/migration/jobs-archive/` (2.5 MB), alongside the migration backups:

| Archived | Why it could not be reconstructed |
|---|---|
| `applications/SCREENING_LOG.md` (432 lines) | The only account of why targets were screened out, in prose. The screening store holds the verdicts; it does not hold the reasoning. |
| `applications/APPLICATION_LOG.md` (353 lines) | The original hand-written log. The ported renderer regenerates a log *from the ledger*; it cannot regenerate narrative that was only ever in this file. |
| `applications/applications.csv` | The JobCopilot export. |
| `applications/records/*.json` (11 files) | The source records the migration read. |
| `applications/<Company>/` | Generated CVs and cover letters as originally filed. |
| `scratchpad/` (828 KB) | Working notes. |
| `DAILY_APPLICATION_RUNBOOK.md.bak`, `daily-apply.sh.bak` | Pre-edit copies. |

Not archived, deliberately: `__pycache__`, `.pytest_cache`, `.playwright-mcp`,
and `.superpowers` (a copy of a shared skills library, not unique to Jobs).

This is a copy, not a migration. It is the safety net for t-5, not a component
of the running system, and nothing reads from it.

### A number worth correcting

`applications.csv` is **1097 lines but 21 data rows** — the fields are
multi-line and quoted. That is very likely where the belief that it held 77
applications came from. All 21 companies were already in the ledger, which is
why importing it was cancelled rather than run.

`agent/RUNBOOK.md` asserted that the previous automation's 77 applications
"are in TruthCV's application history". They are not, and the assertion has
been corrected: what survives is the 21-row export. The rule the agent enforces
now says plainly that absence from the ledger is not evidence that nobody
applied.

## Security posture — pre-existing, not introduced here

Review of this change turned up two things that predate it and are unchanged by
it. Neither is a consequence of the merge, and both are recorded here because
the log's placement was initially justified by reasoning that they undermine.

1. **`GET /api/download/{name}` is unauthenticated** and serves the data volume
   root by bare filename. `applications.json`, `answers.yaml` and
   `canonical_cv.pdf` all sit there under guessable names. Keeping the log one
   directory down puts it beyond *this* route, but the data it contains is
   already reachable through the ledger.
2. **The SPA catch-all route resolves `..` without a containment check**, so
   the subdirectory is not beyond that one. This was reported during review of
   this change and has not been fixed here — fixing a path-traversal in the
   static file handler is not retirement work, and bundling it into this plan
   would hide it.

Every file on the data volume is `0644` and root-owned, including
`applications.json`. The rendered log matches that posture rather than being
made a special case; tightening only the log while the ledger it is rendered
from sits beside it would buy nothing real.

## Data-integrity notes observed while auditing

- Two records reference cover letters absent from the
  Jobs tree. They were already missing before this plan set began.
- Application `245bccd01cae` has `cv_document.source` holding the *cover
  letter* text, identical to `cover_letter_document.source`. Pre-existing data
  defect, carried in from before the migration; not introduced by it.
