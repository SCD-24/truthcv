# TruthCV — Web UI design direction

Applies `.claude/skills/frontend-design/SKILL.md`.

## Subject (pinned)
A single self-hosting job-seeker turns their LinkedIn history into a truthful,
job-tailored CV. The page's one job: walk them from PDF upload to a downloadable
CV **while making trust visible**. The subject's world is the *paper trail of a
career* — records, provenance, the line between what is **attested** and what is
merely **inferred**.

## Thesis / signature
**Provenance is the interface.** Every fact is shown as an entry in an auditable
ledger, carrying a visible stamp of where it came from:

- `ATTESTED · linkedin` — pulled from the uploaded profile
- `CONFIRMED · you` — an inference the user explicitly approved

The verification-green accent appears *only* on attested/confirmed provenance;
rust appears *only* on unverified inferences that need a decision. The accent
never decorates — it always means "this is trustworthy" or "this needs you."
This is the one bold element; everything else stays quiet.

## Palette (5 named)
| token | hex | role |
|-------|-----|------|
| `--ink` | #1B2A4A | iron-indigo — text & structure |
| `--ground` | #EEF1F5 | cool document ground — app background |
| `--surface` | #FBFCFD | raised cards |
| `--attest` | #3A6B5E | verification green — attested/confirmed ONLY |
| `--flag` | #B4532A | rust — inference/unverified, needs attention ONLY |

## Type (3 roles)
- Display: **Space Grotesk** — a grotesque, not a fashionable high-contrast serif.
- Body: **Source Sans 3** — humanist, quiet, legible.
- Utility: **Space Mono** — reserved strictly for provenance stamps, ids, dates
  (the record-keeping voice), never for running copy.

## Layout
```
+----------------+---------------------------------------------+
|  TRUTHCV       |  eyebrow: STEP 2 OF 5                        |
|                |  Review what we found                        |
|  ● Upload      |                                             |
|  ● Review   ◀  |  +---------------------------------------+  |
|  ○ Posting     |  | Senior Engineer · Acme                |  |
|  ○ Confirm     |  | 2021–2024                             |  |
|  ○ Download    |  | ATTESTED · linkedin        [edit]     |  |
|                |  +---------------------------------------+  |
|  the step rail |  +---------------------------------------+  |
|  is itself the |  | Led migration to Kubernetes           |  |
|  record of     |  | CONFIRMED · you            [edit]     |  |
|  progress      |  +---------------------------------------+  |
|                |                                             |
|                |            [ Back ]   [ Save & continue ]   |
+----------------+---------------------------------------------+
```
Fixed left **step rail** (the wizard reads as a record of progress); a centered
content **stage** (max ~760px) holds one step's ledger of provenance-stamped
cards. On mobile the rail collapses to a slim top progress strip.

## Critique against the three generic defaults
- **Default #1 (cream+serif+terracotta):** rejected. A "document" subject tempts
  cream+serif; steered to a *cooler* iron-indigo ink on blue-grey document ground,
  grotesque (not serif) display, green/rust accents that carry meaning.
- **Default #3 (broadsheet hairlines / zero-radius / columns):** the real risk for
  a ledger theme. Rejected: soft radii, card surfaces with depth, mono used only
  for stamps — no newspaper columns, no all-hairline look.
- **Default #2 (near-black + acid accent):** not applicable; nothing acid here.

## Quality floor (non-negotiable)
Responsive to mobile, visible keyboard focus (`--focus` ring, not the accents),
`prefers-reduced-motion` respected, dark-scheme tokens provided. Motion is
deliberate: a step transition and provenance-stamp reveal, nothing scattered.
