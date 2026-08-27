---
name: mui-theme-token-mapping
description: Exact TruthCV design-token → MUI createTheme mapping for the option-2 MUI migration
type: reference
---

For the MUI-themed-to-ledger migration ([[mui-migration-scope]]), map web/src/styles/tokens.css into MUI createTheme. Because tokens flip under @media(prefers-color-scheme:dark), the cleanest approach is a theme that READS the CSS custom properties via `var(--x)` strings so light/dark keeps working automatically. Mapping:
- palette.background.default = var(--ground) #ecede6; palette.background.paper = var(--surface) #f6f7f2
- palette.text.primary = var(--ink) #1a211c; palette.text.secondary = var(--ink-soft) #59615a
- palette.success/attested = var(--attest) #2f5d3e (seal green — ATTESTED only), wash var(--attest-wash)
- palette.error/flag = var(--flag) #9c3b2c (oxblood — unverified/inference only), wash var(--flag-wash)
- palette.primary.main = var(--attest) (primary actions in seal green to keep identity) OR var(--focus) #356fa6; palette.info/focus = var(--focus)
- divider = var(--line) #d2d5cc
- shape.borderRadius = 8 (var(--radius); sm 4, lg 14)
- typography.fontFamily = var(--font-body) "IBM Plex Sans"; headings use var(--font-display) "Schibsted Grotesk"; mono/eyebrows/ids use var(--font-mono) "IBM Plex Mono" with letterSpacing var(--track-eyebrow) 0.14em uppercase
- type scale steps: --step--1 .833rem ... --step-4 2.9rem
- components overrides: MuiButton (radius, no uppercase, seal-green contained), MuiTextField/Select outlined with var(--line) border + var(--focus) focus ring var(--shadow-focus), MuiDialog paper radius var(--radius-lg) shadow var(--shadow-card), MuiCheckbox attest color, MuiAlert severity success=attest/error=flag.
Keep semantic rule: seal-green ONLY for attested/confirmed, oxblood ONLY for unverified/flagged (never decorative).
Deps to add: @mui/material @emotion/react @emotion/styled (and optionally @mui/icons-material). ThemeProvider + CssBaseline wrap in web/src/main.tsx around <App/>. Keep tokens.css imported (theme references its vars). DESIGN.md at web/src/styles/DESIGN.md documents the language — read before restyling.
Surfaces to migrate (all under web-ui component): App.tsx shell + wizard/StepRail.tsx; steps/UploadStep, ReviewStep, PostingStep, ConfirmStep, DownloadStep, DocumentEditor; applications/ApplicationsModal (Table/Dialog/Checkbox/Select); settings/SettingsModal (Dialog/TextField/Select/Button). No test runner in web/. Verify: cd web && npx tsc --noEmit; then npm run build.
