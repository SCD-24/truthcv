import { useEffect, useMemo, useState } from "react";
import Box from "@mui/material/Box";
import Stack from "@mui/material/Stack";
import Button from "@mui/material/Button";
import Paper from "@mui/material/Paper";
import Alert from "@mui/material/Alert";
import Chip from "@mui/material/Chip";
import Typography from "@mui/material/Typography";
import LinearProgress from "@mui/material/LinearProgress";
import CircularProgress from "@mui/material/CircularProgress";
import Table from "@mui/material/Table";
import TableHead from "@mui/material/TableHead";
import TableBody from "@mui/material/TableBody";
import TableRow from "@mui/material/TableRow";
import TableCell from "@mui/material/TableCell";
import TableContainer from "@mui/material/TableContainer";
import ArrowBackIcon from "@mui/icons-material/ArrowBack";
import { listApplications } from "../api/client";
import type { Application } from "../api/types";
import {
  computeInsights,
  type Breakdown,
  type Insights,
  type MonthBucket,
  type SegmentRate,
} from "./insights";
import "../styles/analytics.css";

/** Format a 0–1 rate as a whole-number percentage. */
function pct(rate: number): string {
  return `${Math.round(rate * 100)}%`;
}

/**
 * The analytics view — the outbound ledger read back as insight.
 *
 * A full page inside the wizard stage (mirroring ApplicationsPage): it loads the
 * same `Application[]` via `listApplications()` with loading/error/empty states,
 * then renders the pure `computeInsights` snapshot. The accent carries meaning —
 * seal-green (var(--attest)) marks responded/positive figures, oxblood
 * (var(--flag)) marks stale or gap states — and never decorates. `onBack`
 * returns to the wizard step the user left.
 */
export function AnalyticsPage({ onBack }: { onBack: () => void }) {
  const [apps, setApps] = useState<Application[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    listApplications()
      .then(setApps)
      .catch((e) =>
        setError(e instanceof Error ? e.message : "Couldn't load applications."),
      )
      .finally(() => setLoading(false));
  }, []);

  const insights = useMemo(() => computeInsights(apps), [apps]);

  return (
    <Box className="analytics-page" aria-labelledby="analytics-title">
      <Stack
        direction="row"
        className="analytics-page__head"
        sx={{ mb: 3, alignItems: "flex-start", justifyContent: "space-between", gap: 2 }}
      >
        <Box>
          <Typography variant="overline" className="analytics__eyebrow" sx={{ display: "block" }}>
            Ledger insight
          </Typography>
          <Typography
            id="analytics-title"
            variant="h4"
            component="h1"
            className="analytics-page__title"
          >
            Analytics
          </Typography>
        </Box>
        <Button variant="text" startIcon={<ArrowBackIcon fontSize="small" />} onClick={onBack}>
          Back to wizard
        </Button>
      </Stack>

      {error && (
        <Alert severity="error" sx={{ mb: 2 }}>
          {error}
        </Alert>
      )}

      {loading ? (
        <Stack direction="row" spacing={2} sx={{ py: 6, justifyContent: "center" }}>
          <CircularProgress size={20} sx={{ color: "var(--attest)" }} />
          <Typography color="text.secondary">Reading the ledger…</Typography>
        </Stack>
      ) : apps.length === 0 ? (
        <Typography color="text.secondary" sx={{ py: 6, textAlign: "center" }}>
          No applications yet. Track a few in the Applications ledger and the
          numbers will show up here.
        </Typography>
      ) : (
        <InsightsView insights={insights} />
      )}
    </Box>
  );
}

/** The assembled analytics sections for a non-empty ledger. */
function InsightsView({ insights }: { insights: Insights }) {
  const { totals, rates } = insights;
  return (
    <Stack spacing={4}>
      <Box className="analytics__cards">
        <StatCard label="Total tracked" value={`${totals.total}`} sub={`${totals.drafts} drafts`} />
        <StatCard label="Submitted" value={`${totals.submitted}`} sub={pct(rates.docAttachRate) + " have a doc"} />
        <RateCard label="Response rate" rate={rates.responseRate} positive />
        <RateCard label="Outreach rate" rate={rates.outreachRate} />
      </Box>

      <ResponseByOutreachPanel insights={insights} />
      <BreakdownPanel title="By status" rows={insights.byStatus} />
      <BreakdownPanel title="By submission type" rows={insights.bySubmissionType} />
      <BreakdownPanel title="By method" rows={insights.byMethod} />
      <TimeSeriesPanel series={insights.timeSeries} />
      <AttentionPanel insights={insights} />
    </Stack>
  );
}

/** A single headline figure card. */
function StatCard({ label, value, sub }: { label: string; value: string; sub?: string }) {
  return (
    <Paper variant="outlined" sx={{ p: 2.5 }}>
      <div className="analytics__stat-label">{label}</div>
      <div className="analytics__stat-value">{value}</div>
      {sub && <div className="analytics__stat-sub">{sub}</div>}
    </Paper>
  );
}

/** A headline rate card, with a themed progress bar. Positive rates read
 * seal-green; neutral rates use the default track. */
function RateCard({ label, rate, positive }: { label: string; rate: number; positive?: boolean }) {
  return (
    <Paper variant="outlined" sx={{ p: 2.5 }}>
      <div className="analytics__stat-label">{label}</div>
      <div className="analytics__stat-value">{pct(rate)}</div>
      <LinearProgress
        variant="determinate"
        value={Math.round(rate * 100)}
        sx={{
          mt: 1,
          height: 6,
          borderRadius: 3,
          ...(positive && { "& .MuiLinearProgress-bar": { bgcolor: "var(--attest)" } }),
        }}
      />
    </Paper>
  );
}

/** Response rate split by whether the user reached out. */
function ResponseByOutreachPanel({ insights }: { insights: Insights }) {
  const { withOutreach, withoutOutreach } = insights.responseByOutreach;
  return (
    <Paper variant="outlined" sx={{ p: 3 }}>
      <SectionTitle>Response by outreach</SectionTitle>
      <Stack direction={{ xs: "column", sm: "row" }} spacing={4} sx={{ mt: 2 }}>
        <OutreachStat label="With outreach" seg={withOutreach} />
        <OutreachStat label="Without outreach" seg={withoutOutreach} />
      </Stack>
    </Paper>
  );
}

/** One outreach-segment response figure. */
function OutreachStat({ label, seg }: { label: string; seg: SegmentRate }) {
  return (
    <Box sx={{ flex: 1 }}>
      <div className="analytics__stat-label">{label}</div>
      <div className="analytics__stat-value" style={{ color: "var(--attest)" }}>
        {pct(seg.rate)}
      </div>
      <div className="analytics__stat-sub">
        {seg.responded} of {seg.submitted} submitted replied
      </div>
    </Box>
  );
}

/** A breakdown table showing per-segment response rate. */
function BreakdownPanel({ title, rows }: { title: string; rows: Breakdown[] }) {
  if (rows.length === 0) return null;
  return (
    <Paper variant="outlined" sx={{ p: 3 }}>
      <SectionTitle>{title}</SectionTitle>
      <TableContainer sx={{ mt: 1 }}>
        <Table size="small">
          <TableHead>
            <TableRow>
              <TableCell>Segment</TableCell>
              <TableCell align="right">Count</TableCell>
              <TableCell align="right">Submitted</TableCell>
              <TableCell align="right">Replied</TableCell>
              <TableCell align="right">Response rate</TableCell>
            </TableRow>
          </TableHead>
          <TableBody>
            {rows.map((row) => (
              <BreakdownRow key={row.label} row={row} />
            ))}
          </TableBody>
        </Table>
      </TableContainer>
    </Paper>
  );
}

/** One breakdown row with its guarded per-segment response rate. */
function BreakdownRow({ row }: { row: Breakdown }) {
  const rate = row.submitted > 0 ? row.responded / row.submitted : 0;
  return (
    <TableRow hover>
      <TableCell>{row.label}</TableCell>
      <TableCell align="right">{row.count}</TableCell>
      <TableCell align="right">{row.submitted}</TableCell>
      <TableCell align="right">{row.responded}</TableCell>
      <TableCell align="right">
        <Chip
          size="small"
          variant="outlined"
          label={pct(rate)}
          color={row.responded > 0 ? "success" : "default"}
        />
      </TableCell>
    </TableRow>
  );
}

/** A per-month applications bar chart: applied columns with the responded
 * portion stamped seal-green. */
function TimeSeriesPanel({ series }: { series: MonthBucket[] }) {
  if (series.length === 0) return null;
  const peak = Math.max(...series.map((b) => b.applied), 1);
  return (
    <Paper variant="outlined" sx={{ p: 3 }}>
      <SectionTitle>Applications per month</SectionTitle>
      <div className="analytics__chart">
        {series.map((bucket) => (
          <MonthColumn key={bucket.month} bucket={bucket} peak={peak} />
        ))}
      </div>
    </Paper>
  );
}

/** One month's column: total applied height, responded portion in seal-green. */
function MonthColumn({ bucket, peak }: { bucket: MonthBucket; peak: number }) {
  const height = Math.round((bucket.applied / peak) * 100);
  const respondedPct = bucket.applied > 0 ? (bucket.responded / bucket.applied) * 100 : 0;
  return (
    <div className="analytics__bar-col">
      <span className="analytics__bar-count">{bucket.applied}</span>
      <div className="analytics__bar-stack">
        <div className="analytics__bar" style={{ height: `${Math.max(height, 2)}%` }}>
          <div className="analytics__bar-responded" style={{ height: `${respondedPct}%` }} />
        </div>
      </div>
      <span className="analytics__bar-label">{bucket.month}</span>
    </div>
  );
}

/** Needs-attention list and data-quality gaps — both oxblood-flagged states. */
function AttentionPanel({ insights }: { insights: Insights }) {
  const { needsAttention, dataGaps } = insights;
  return (
    <Paper variant="outlined" sx={{ p: 3 }}>
      <SectionTitle>Needs attention</SectionTitle>
      {needsAttention.length === 0 ? (
        <Typography variant="body2" color="text.secondary" sx={{ mt: 1 }}>
          No submitted applications are overdue for a follow-up.
        </Typography>
      ) : (
        <Stack spacing={1} sx={{ mt: 1 }}>
          {needsAttention.map((app) => (
            <Alert key={app.id} severity="warning" icon={false}>
              <strong>{app.company || "—"}</strong> — submitted{" "}
              {app.applicationDate || "with no date"}, still no response.
            </Alert>
          ))}
        </Stack>
      )}

      <SectionTitle sx={{ mt: 3 }}>Data gaps</SectionTitle>
      {dataGaps.length === 0 ? (
        <Typography variant="body2" color="text.secondary" sx={{ mt: 1 }}>
          Every application has a website, an application URL, and a document.
        </Typography>
      ) : (
        <Stack spacing={1} sx={{ mt: 1 }}>
          {dataGaps.map((gap) => (
            <Stack
              key={gap.id}
              direction="row"
              spacing={1}
              sx={{ alignItems: "center", flexWrap: "wrap" }}
            >
              <Typography variant="body2" sx={{ fontWeight: 500 }}>
                {gap.company}
              </Typography>
              {gap.missing.map((m) => (
                <Chip
                  key={m}
                  size="small"
                  variant="outlined"
                  label={`missing ${m}`}
                  sx={{
                    color: "var(--flag)",
                    borderColor: "var(--flag)",
                    fontFamily: "var(--font-mono)",
                  }}
                />
              ))}
            </Stack>
          ))}
        </Stack>
      )}
    </Paper>
  );
}

/** A mono record-voice section heading. */
function SectionTitle({
  children,
  sx,
}: {
  children: React.ReactNode;
  sx?: object;
}) {
  return (
    <Typography
      variant="subtitle2"
      sx={{
        fontFamily: "var(--font-mono)",
        letterSpacing: "var(--track-eyebrow)",
        textTransform: "uppercase",
        color: "var(--ink-soft)",
        ...sx,
      }}
    >
      {children}
    </Typography>
  );
}
