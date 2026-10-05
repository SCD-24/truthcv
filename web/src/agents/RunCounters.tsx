import Stack from "@mui/material/Stack";
import Tooltip from "@mui/material/Tooltip";
import Typography from "@mui/material/Typography";
import type { RunRecord } from "../api/types";

function Counter({ label, value, tip }: { label: string; value: string | number; tip: string }) {
  return (
    <Tooltip title={tip} arrow>
      <Typography variant="caption" color="text.secondary" tabIndex={0}>
        {label}: {value}
      </Typography>
    </Tooltip>
  );
}

/** The per-run counter row on a run card. While the run is still going the
 * numbers are partial, so the row says so. */
export function RunCounters({
  run,
  capLabel,
  isRunning,
}: {
  run: RunRecord;
  capLabel: string;
  isRunning: boolean;
}) {
  return (
    <Stack direction="row" spacing={2} sx={{ mt: 0.5, flexWrap: "wrap" }}>
      <Counter
        label="Postings seen"
        value={run.postingsSeen}
        tip="Unique job postings found by discovery this run"
      />
      <Counter
        label="Screenings recorded"
        value={run.screeningsRecorded}
        tip="Postings checked against your profiles"
      />
      <Counter
        label="Couldn't read"
        value={run.blockedCount}
        tip="Postings whose page could not be read (sign-in wall, dead link, redirect page) — no verdict was reached"
      />
      <Counter
        label="Queued for approval"
        value={run.queuedForApproval}
        tip="Waiting for your decision on the Approvals page"
      />
      <Counter label="Applied" value={capLabel} tip="Applications submitted this run" />
      {run.overCapWrites > 0 && (
        <Typography variant="caption" color="warning.main">
          Over cap: {run.overCapWrites}
        </Typography>
      )}
      {(run.itemsFailed ?? 0) > 0 && (
        <Typography variant="caption" color="warning.main">
          Items failed: {run.itemsFailed}
        </Typography>
      )}
      {isRunning && (
        <Typography variant="caption" color="text.secondary">
          (so far)
        </Typography>
      )}
    </Stack>
  );
}
