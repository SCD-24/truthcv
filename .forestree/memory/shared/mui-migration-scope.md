---
name: mui-migration-scope
description: The TruthCV MUI adoption is option 2: MUI themed to the existing ledger tokens, identity preserved
type: project
---

User asked to "convert to react and use mui" — the app is ALREADY React (see [[web-ui-stack-and-design-system]]); the real work is adopting MUI. User chose OPTION 2: bring in MUI (@mui/material + @emotion) but configure createTheme from the existing design tokens in web/src/styles/tokens.css so the "provenance ledger" aesthetic is preserved (mono record-voice typography, seal-green var(--attest) attested state, oxblood var(--flag) unverified/flag state, radii/spacing scale). NOT stock Material Design, NOT partial. Plan is component-scoped under the web-ui component: theme setup first (ThemeProvider in main.tsx/App.tsx, tokens->theme palette+typography+shape+component defaults), then migrate each surface (App shell, wizard StepRail+steps Upload/Review/Posting/Confirm/Download, DocumentEditor, ApplicationsModal, SettingsModal) to MUI components (Button, TextField, Select, Dialog, Table, Checkbox, Alert) while keeping ledger semantics. web/ has NO test runner. Verify with `cd web && npx tsc --noEmit` and a vite build. This is component-scoped to web-ui only; needs plan_component_work then user starts the build.
