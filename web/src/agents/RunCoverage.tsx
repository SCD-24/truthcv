import Typography from "@mui/material/Typography";
import type { DiscoveryCoverage } from "../api/types";

/** Human-readable label for a discovery-coverage status, e.g. "login_walled"
 * -> "login-walled". Mirrors the values agenttools/tools_runs.py accepts. */
function statusLabel(status: DiscoveryCoverage["status"]): string {
  return status.replace(/_/g, "-");
}

/** "3 searched, 2 login-walled" — one clause per status present, in a fixed
 * order, so the same run always reads the same way. Statuses absent from the
 * channel's entries are omitted rather than shown as "0 empty". */
function summariseByStatus(entries: DiscoveryCoverage[]): string {
  const order: DiscoveryCoverage["status"][] = ["searched", "empty", "login_walled", "skipped"];
  const counts = new Map<string, number>();
  for (const entry of entries) {
    counts.set(entry.status, (counts.get(entry.status) ?? 0) + 1);
  }
  return order
    .filter((status) => (counts.get(status) ?? 0) > 0)
    .map((status) => `${counts.get(status)} ${statusLabel(status)}`)
    .join(", ");
}

/** One channel's clause: "not reached" when the run never touched it, else
 * the channel-appropriate summary. Feed reports a postings total (that
 * channel has no meaningful "searched"/"empty" distinction — it is a list
 * the agent is handed, not something it can fail to reach); direct boards
 * and dork queries report status counts, since those are worked one board
 * or query at a time and can be login-walled or skipped. */
function channelClause(label: string, channel: DiscoveryCoverage["channel"], entries: DiscoveryCoverage[]): string {
  const forChannel = entries.filter((entry) => entry.channel === channel);
  if (forChannel.length === 0) return `${label}: not reached`;
  if (channel === "feed") {
    const postings = forChannel.reduce((sum, entry) => sum + entry.postingsFound, 0);
    return `${label}: ${postings} posting${postings === 1 ? "" : "s"}`;
  }
  return `${label}: ${summariseByStatus(forChannel)}`;
}

/** Per-run discovery coverage, rendered as one caption line summarising
 * every channel — feed, direct boards, dork queries — so a board or query
 * the agent never reached (an empty channel) reads visibly differently from
 * one it worked and found nothing on. */
export function RunCoverage({ coverage }: { coverage: DiscoveryCoverage[] }) {
  if (coverage.length === 0) {
    return (
      <Typography variant="caption" color="text.secondary" sx={{ display: "block", mt: 0.5 }}>
        Discovery coverage: none recorded
      </Typography>
    );
  }

  const clauses = [
    channelClause("Feed", "feed", coverage),
    channelClause("Direct boards", "direct", coverage),
    channelClause("Dorks", "dork", coverage),
  ];

  return (
    <Typography variant="caption" color="text.secondary" sx={{ display: "block", mt: 0.5 }}>
      {clauses.join(" · ")}
    </Typography>
  );
}
