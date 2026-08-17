# Agent target list — template

**`agent/targets.md` is gitignored** (see `.gitignore`) and does not ship with
this repo. It is a personal research queue — the companies and roles an
operator has already scouted, with the evidence for each — and it is expected
to contain a phone number's worth of judgement calls and commentary that has
no business being committed to a public repo. Each operator maintains their
own copy on disk; the agent and this project never read or write it
automatically.

This file is that copy's template. It documents the **shape** the real file
takes — headings and per-entry fields — using invented companies, roles and
URLs only. Copy it to `agent/targets.md` and replace every row with your own
research.

---

## Target queue

A single wide table, one row per candidate posting. Columns, left to right:

`Pri | Company | Role title | Location field (exact) | Remote model | Salary | Language | Stack / fit note | URL | Source | Applied? | Date | Outcome | Next action`

- **Pri** — a rough priority tier (`1` = pursue first), your own scale.
- **Company / Role title** — as posted.
- **Location field (exact)** — copied verbatim from the posting, not
  normalised — postings contradict themselves and that's worth preserving.
- **Remote model** — what the posting actually says about remote/hybrid, not
  what the job board tagged it as.
- **Salary** — the stated band, or `not stated`.
- **Language** — the posting's stated working-language requirement.
- **Stack / fit note** — why this one is worth a look.
- **URL / Source** — the posting link and where you found it (company ATS,
  aggregator, LinkedIn, etc.).
- **Applied? / Date / Outcome / Next action** — a hand-maintained snapshot
  only. It goes stale fast — the authoritative record of what has actually
  been applied to, screened out, or is in cooldown lives in TruthCV's own
  application ledger and screening store, not in this table. Treat these
  columns as scratch notes for your own research, never as something the
  agent should trust over the ledger.

Example rows (fictional):

| Pri | Company | Role title | Location field (exact) | Remote model | Salary | Language | Stack / fit note | URL | Source | Applied? | Date | Outcome | Next action |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| 1 | Northwind Analytics | Senior Data Engineer (Remote) | EMEA - Distributed | Fully remote | EUR 90,000-110,000 | English | dbt/Airflow stack match | https://example.com/jobs/northwind-senior-data-engineer | example-boards.test |  |  |  |  |
| 2 | Contoso Cloud | Platform Engineer (m/f/d) | Berlin | Remote-friendly, unconfirmed | not stated | English | Posting mentions agentic workflow tooling | https://jobs.example-ats.test/contoso/platform-engineer | Example ATS |  |  |  |  |

---

## Research and reasoning

A free-form section for the write-up behind the table above: what you found,
what you ruled out, and why. There is no fixed structure here beyond
whatever headings help you organise it — the real file, for reference, groups
this into subsections such as:

- a top-line finding that reframes the search, if there is one
- roles worth applying to this cycle, one subsection per company, with the
  concrete evidence for each (posting language, salary, stack fit)
- companies confirmed to hire in your target country/entity but with nothing
  open right now, worth revisiting
- roles rejected outright, grouped by the reason (pay floor, language
  requirement, employer no longer exists, wrong remote model, etc.)
- notes on method — what sources you used, what you couldn't verify, and any
  research-tool limits you hit
- a short strategic takeaway, if the research changes which roles you should
  lead with

None of that structure is enforced by the agent — it never parses this file.
It exists purely so the person maintaining it (you) can think out loud in one
place before distilling rows into the table above.
