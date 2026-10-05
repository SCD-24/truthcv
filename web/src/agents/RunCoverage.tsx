import { Fragment, type ReactNode } from "react";
import Box from "@mui/material/Box";
import Tooltip from "@mui/material/Tooltip";
import Typography from "@mui/material/Typography";
import type { DiscoveryCoverage, RunRecord } from "../api/types";

type Status = DiscoveryCoverage["status"];

/** Longest board reason shown in a tooltip before it is cut with an ellipsis. */
export const MAX_REASON_CHARS = 120;

const STATUS_LABELS: Record<Status, string> = {
  searched: "searched",
  empty: "no matches",
  extraction_failed: "couldn't find job links",
  login_walled: "sign-in required",
  blocked: "blocked by the site",
  skipped: "not tried",
};

const STATUS_EXPLANATIONS: Record<Status, string> = {
  searched: "Searched: the board was reached and its results were read.",
  empty: "No matches: the board was searched but returned no postings.",
  extraction_failed: "Couldn't find job links: the page loaded but no job links could be extracted.",
  login_walled: "Sign-in required: the board needs you to be signed in.",
  blocked: "Blocked by the site: the site refused the automated request.",
  skipped: "Not tried: the agent never attempted this board or query.",
};

/** Statuses whose counts are drawn attention to, and whose entries are listed
 * with their reason in the tooltip. */
const PROBLEM_STATUSES: Status[] = ["blocked", "extraction_failed"];
const DETAIL_STATUSES: Status[] = ["blocked", "extraction_failed", "empty"];

const STATUS_ORDER: Status[] = [
  "searched",
  "blocked",
  "extraction_failed",
  "empty",
  "login_walled",
  "skipped",
];

function statusLabel(status: Status): string {
  return STATUS_LABELS[status] ?? status;
}

function truncate(text: string): string {
  return text.length > MAX_REASON_CHARS ? `${text.slice(0, MAX_REASON_CHARS - 1)}…` : text;
}

function countByStatus(entries: DiscoveryCoverage[]): Map<Status, number> {
  const counts = new Map<Status, number>();
  for (const entry of entries) {
    counts.set(entry.status, (counts.get(entry.status) ?? 0) + 1);
  }
  return counts;
}

function Problem({ children }: { children: ReactNode }) {
  return (
    <Box component="span" sx={{ color: "warning.main" }}>
      {children}
    </Box>
  );
}

/** "3 searched, 2 sign-in required" — one segment per status present, in a
 * fixed order. Problem statuses are tinted. */
function StatusSummary({ entries }: { entries: DiscoveryCoverage[] }) {
  const counts = countByStatus(entries);
  const present = STATUS_ORDER.filter((status) => (counts.get(status) ?? 0) > 0);
  return (
    <>
      {present.map((status, i) => {
        const text = `${counts.get(status)} ${statusLabel(status)}`;
        return (
          <Fragment key={status}>
            {i > 0 ? ", " : null}
            {PROBLEM_STATUSES.includes(status) ? <Problem>{text}</Problem> : text}
          </Fragment>
        );
      })}
    </>
  );
}

function ClauseTooltip({ entries }: { entries: DiscoveryCoverage[] }) {
  const counts = countByStatus(entries);
  const present = STATUS_ORDER.filter((status) => (counts.get(status) ?? 0) > 0);
  const details = entries.filter((entry) => DETAIL_STATUSES.includes(entry.status));
  return (
    <Box>
      {present.map((status) => (
        <Typography key={status} variant="caption" sx={{ display: "block" }}>
          {STATUS_EXPLANATIONS[status]}
        </Typography>
      ))}
      {details.map((entry, i) => (
        <Typography key={`${entry.board}-${i}`} variant="caption" sx={{ display: "block", mt: i === 0 ? 0.5 : 0 }}>
          {`${entry.board} (${statusLabel(entry.status)})${entry.reason ? `: ${truncate(entry.reason)}` : ""}`}
        </Typography>
      ))}
    </Box>
  );
}

function isGoogleBlocked(entries: DiscoveryCoverage[]): boolean {
  return (
    entries.every((entry) => entry.status === "blocked" || entry.status === "skipped") &&
    entries.some((entry) => /google/i.test(entry.reason))
  );
}

/** One channel's clause: "not reached" when the run never touched it, else
 * the channel-appropriate summary. Feed reports a postings total; direct
 * boards and dork queries report status counts. */
function ChannelClause({
  label,
  channel,
  entries,
}: {
  label: string;
  channel: DiscoveryCoverage["channel"];
  entries: DiscoveryCoverage[];
}) {
  const forChannel = entries.filter((entry) => entry.channel === channel);
  if (forChannel.length === 0) {
    return (
      <Tooltip title="Not reached: the run never touched this channel." arrow>
        <span tabIndex={0}>{`${label}: not reached`}</span>
      </Tooltip>
    );
  }
  let body: ReactNode;
  if (channel === "feed") {
    const postings = forChannel.reduce((sum, entry) => sum + entry.postingsFound, 0);
    body = `${postings} posting${postings === 1 ? "" : "s"}`;
  } else if (channel === "dork" && isGoogleBlocked(forChannel)) {
    const counts = countByStatus(forChannel);
    body = (
      <>
        <Problem>Google blocked the searches</Problem>
        {` (${counts.get("blocked") ?? 0} blocked, ${counts.get("skipped") ?? 0} not tried)`}
      </>
    );
  } else {
    body = <StatusSummary entries={forChannel} />;
  }
  return (
    <Tooltip title={<ClauseTooltip entries={forChannel} />} arrow>
      <span tabIndex={0}>
        {label}: {body}
      </span>
    </Tooltip>
  );
}

/** Per-run discovery coverage, rendered as one caption line summarising
 * every channel — feed, direct boards, dork queries — so a board or query
 * the agent never reached (an empty channel) reads visibly differently from
 * one it worked and found nothing on. */
export function RunCoverage({ coverage, status }: { coverage: DiscoveryCoverage[]; status?: RunRecord["status"] }) {
  if (coverage.length === 0) {
    return (
      <Typography variant="caption" color="text.secondary" sx={{ display: "block", mt: 0.5 }}>
        {status === "failed" || status === "cancelled"
          ? "Discovery coverage: none recorded before the run stopped"
          : "Discovery coverage: none recorded"}
      </Typography>
    );
  }

  const clauses: [string, DiscoveryCoverage["channel"]][] = [
    ["Feed", "feed"],
    ["Direct boards", "direct"],
    ["Dorks", "dork"],
  ];

  return (
    <Typography
      variant="caption"
      color="text.secondary"
      data-testid="run-coverage"
      sx={{ display: "block", mt: 0.5 }}
    >
      {clauses.map(([label, channel], i) => (
        <Fragment key={channel}>
          {i > 0 ? " · " : null}
          <ChannelClause label={label} channel={channel} entries={coverage} />
        </Fragment>
      ))}
    </Typography>
  );
}
