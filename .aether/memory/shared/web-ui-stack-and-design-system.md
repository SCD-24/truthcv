---
name: web-ui-stack-and-design-system
description: TruthCV web/ is already React+Vite+TS with a bespoke "provenance ledger" CSS design system
type: project
---

The TruthCV frontend (web/) is ALREADY React 18 + Vite + TypeScript (all .tsx). There is no "convert to React" needed. It uses a hand-rolled CSS design system (web/src/styles/: tokens.css, global.css, shell.css, step.css, settings.css, applications.css, editor.css) documented in web/src/styles/DESIGN.md — a deliberate "provenance ledger" visual language (mono "record voice", seal-green var(--attest) for attested/confirmed states, oxblood var(--flag) for unverified). Components: App.tsx, wizard/ (StepRail, steps, store.tsx = useWizard context), steps/*.tsx (Upload/Review/Posting/Confirm/Download + DocumentEditor), applications/ApplicationsModal.tsx, settings/SettingsModal.tsx. No component library (no MUI). Pinned memory web-ui-uses-frontend-design-skill says user wants the frontend-design skill applied and the ledger aesthetic preserved. So a request to "use MUI" conflicts with the existing bespoke design system — confirm scope before any wholesale rewrite.
