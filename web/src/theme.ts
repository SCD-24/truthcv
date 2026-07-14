import { createTheme } from "@mui/material/styles";

/**
 * MUI theme for TruthCV — the "provenance ledger" design language expressed as
 * an MUI theme rather than stock Material Design.
 *
 * Why reference CSS custom properties (`var(--x)`) instead of hard-coding hexes:
 * tokens.css flips every colour under `@media (prefers-color-scheme: dark)`.
 * By pointing the theme at the vars, light/dark keeps working for free and
 * tokens.css stays the single source of truth for the palette.
 *
 * Semantic rule carried over from DESIGN.md and preserved everywhere:
 *   - seal-green (--attest) means ATTESTED / user-confirmed provenance ONLY
 *   - oxblood (--flag) means inference / unverified ONLY
 * Neither colour is ever decorative.
 */

const mono = 'var(--font-mono)';
const body = 'var(--font-body)';
const display = 'var(--font-display)';

export const theme = createTheme({
  cssVariables: false,
  palette: {
    // createTheme augments each colour at module-eval time (computing
    // light/dark/contrastText), which requires a PARSEABLE colour — a raw
    // `var(--x)` string throws and blanks the whole app. So the palette carries
    // concrete light-mode hexes from tokens.css here; dark-mode flipping is
    // handled where it visibly matters by the `var(--x)` references in the
    // component styleOverrides/variants below (those are applied as CSS at
    // paint time, so they follow prefers-color-scheme for free).
    background: { default: '#ecede6', paper: '#f6f7f2' },
    text: { primary: '#1a211c', secondary: '#59615a' },
    primary: { main: '#2f5d3e', contrastText: '#f6f7f2' },
    success: { main: '#2f5d3e', contrastText: '#f6f7f2' },
    error: { main: '#9c3b2c', contrastText: '#f6f7f2' },
    info: { main: '#356fa6', contrastText: '#f6f7f2' },
    divider: '#d2d5cc',
  },
  shape: { borderRadius: 8 },
  typography: {
    fontFamily: body,
    // Headings wear the editorial grotesque; body/controls stay institutional.
    h1: { fontFamily: display, fontWeight: 700, fontSize: 'var(--step-4)', lineHeight: 'var(--leading-tight)' },
    h2: { fontFamily: display, fontWeight: 700, fontSize: 'var(--step-3)', lineHeight: 'var(--leading-tight)' },
    h3: { fontFamily: display, fontWeight: 700, fontSize: 'var(--step-2)', lineHeight: 'var(--leading-tight)' },
    h4: { fontFamily: display, fontWeight: 500, fontSize: 'var(--step-1)' },
    body1: { fontSize: 'var(--step-0)', lineHeight: 'var(--leading-body)' },
    body2: { fontSize: 'var(--step--1)', lineHeight: 'var(--leading-body)' },
    button: { textTransform: 'none', fontWeight: 500 },
    // The "record voice": ids, dates, provenance stamps, eyebrows.
    overline: {
      fontFamily: mono,
      fontSize: 'var(--step--1)',
      letterSpacing: 'var(--track-eyebrow)',
      textTransform: 'uppercase',
      lineHeight: 1.4,
    },
  },
  components: {
    MuiCssBaseline: {
      styleOverrides: {
        body: {
          backgroundColor: 'var(--ground)',
          color: 'var(--ink)',
        },
      },
    },
    MuiButton: {
      defaultProps: { disableElevation: true },
      styleOverrides: {
        root: { borderRadius: 'var(--radius)', textTransform: 'none', fontWeight: 500 },
        outlined: { borderColor: 'var(--line)', color: 'var(--ink)' },
      },
      variants: [
        {
          props: { variant: 'contained', color: 'primary' },
          style: { backgroundColor: 'var(--attest)', color: 'var(--surface)' },
        },
      ],
    },
    MuiOutlinedInput: {
      styleOverrides: {
        root: {
          borderRadius: 'var(--radius)',
          backgroundColor: 'var(--surface)',
          '& .MuiOutlinedInput-notchedOutline': { borderColor: 'var(--line)' },
          '&:hover .MuiOutlinedInput-notchedOutline': { borderColor: 'var(--ink-soft)' },
          '&.Mui-focused .MuiOutlinedInput-notchedOutline': { borderColor: 'var(--focus)' },
          '&.Mui-focused': { boxShadow: 'var(--shadow-focus)' },
        },
        input: { color: 'var(--ink)' },
      },
    },
    MuiInputLabel: { styleOverrides: { root: { color: 'var(--ink-soft)', '&.Mui-focused': { color: 'var(--focus)' } } } },
    MuiDialog: {
      styleOverrides: {
        paper: {
          borderRadius: 'var(--radius-lg)',
          boxShadow: 'var(--shadow-card)',
          backgroundColor: 'var(--ground)',
          backgroundImage: 'none',
        },
      },
    },
    MuiPaper: { styleOverrides: { root: { backgroundImage: 'none' } } },
    MuiCheckbox: { styleOverrides: { root: { color: 'var(--ink-soft)', '&.Mui-checked': { color: 'var(--attest)' } } } },
    MuiRadio: { styleOverrides: { root: { color: 'var(--ink-soft)', '&.Mui-checked': { color: 'var(--attest)' } } } },
    MuiAlert: {
      styleOverrides: {
        root: { borderRadius: 'var(--radius)' },
      },
      variants: [
        {
          props: { severity: 'success', variant: 'standard' },
          style: { backgroundColor: 'var(--attest-wash)', color: 'var(--attest)' },
        },
        {
          props: { severity: 'error', variant: 'standard' },
          style: { backgroundColor: 'var(--flag-wash)', color: 'var(--flag)' },
        },
      ],
    },
    MuiChip: { styleOverrides: { root: { fontFamily: mono, letterSpacing: '0.06em', textTransform: 'uppercase', fontSize: '0.68rem' } } },
    MuiTableCell: {
      styleOverrides: {
        root: { borderColor: 'var(--line)', color: 'var(--ink)' },
        head: {
          fontFamily: mono,
          textTransform: 'uppercase',
          letterSpacing: 'var(--track-eyebrow)',
          fontSize: '0.72rem',
          color: 'var(--ink-soft)',
        },
      },
    },
    MuiLink: { styleOverrides: { root: { color: 'var(--focus)', textDecorationColor: 'var(--focus)' } } },
    MuiDivider: { styleOverrides: { root: { borderColor: 'var(--line)' } } },
  },
});
