import { useState } from "react";
import {
  Dialog,
  DialogTitle,
  DialogContent,
  DialogActions,
  Table,
  TableHead,
  TableBody,
  TableRow,
  TableCell,
  Button,
  Typography,
  Box,
  Alert,
} from "@mui/material";
import type { RunRecord, BoardBreakdown, RunStopResult } from "../api/types";
import { stopRun } from "../api/client";
import { ButtonSpinner } from "../components/ButtonSpinner";

interface RunDetailModalProps {
  run: RunRecord;
  timeZone?: string;
  onClose: () => void;
  onStopped?: (result: RunStopResult) => void;
}

const STOP_OUTCOME_MESSAGES: Record<RunStopResult["outcome"], string> = {
  cancelling: "Stop requested — the agent is shutting the run down.",
  closed: "No live process owned this run; it was closed as failed (orphaned).",
};

/** Encapsulates the stop-run request lifecycle so RunDetailModal stays small. */
function useStopRun(runId: string, onStopped?: (result: RunStopResult) => void) {
  const [stopping, setStopping] = useState(false);
  const [stopError, setStopError] = useState<string | null>(null);
  const [stopMessage, setStopMessage] = useState<string | null>(null);

  const handleStop = async () => {
    setStopping(true);
    setStopError(null);
    setStopMessage(null);
    try {
      const result = await stopRun(runId);
      setStopMessage(STOP_OUTCOME_MESSAGES[result.outcome]);
      onStopped?.(result);
    } catch (err) {
      setStopError(err instanceof Error ? err.message : String(err));
    } finally {
      setStopping(false);
    }
  };

  return { stopping, stopError, stopMessage, handleStop };
}

interface StopRunButtonProps {
  runId: string;
  stopping: boolean;
  onClick: () => void;
}

/** The Stop button itself; RunDetailModal only renders it for a running run. */
function StopRunButton({ runId, stopping, onClick }: StopRunButtonProps) {
  return (
    <Button onClick={onClick} disabled={stopping} color="warning" variant="outlined" aria-label={`Stop run ${runId}`}>
      {stopping ? (
        <>
          <ButtonSpinner size={14} />
          Stopping…
        </>
      ) : (
        "Stop run"
      )}
    </Button>
  );
}

/**
 * Dialog displaying a run's details: status, timestamps, and a per-board
 * breakdown of screenings with counts for postings seen, for review, and
 * rejected.
 */
export function RunDetailModal({ run, timeZone, onClose, onStopped }: RunDetailModalProps) {
  const [open] = useState(true);
  const { stopping, stopError, stopMessage, handleStop } = useStopRun(run.id, onStopped);

  const formatInZone = (isoString: string, zone?: string): string => {
    if (!isoString) return "";
    try {
      const date = new Date(isoString);
      if (!zone) return date.toLocaleString();
      return date.toLocaleString("en-US", { timeZone: zone });
    } catch {
      return isoString;
    }
  };

  const hasBreakdown = run.boardBreakdown && run.boardBreakdown.length > 0;

  const totals = run.boardBreakdown
    ? run.boardBreakdown.reduce(
        (acc, entry) => ({
          postingsSeen: acc.postingsSeen + entry.postingsSeen,
          forReview: acc.forReview + entry.forReview,
          rejected: acc.rejected + entry.rejected,
        }),
        { postingsSeen: 0, forReview: 0, rejected: 0 }
      )
    : { postingsSeen: 0, forReview: 0, rejected: 0 };

  return (
    <Dialog open={open} onClose={onClose} maxWidth="sm" fullWidth aria-labelledby="run-detail-title">
      <DialogTitle id="run-detail-title">Run <Box component="span" sx={{ fontFamily: "var(--font-mono)", fontSize: "0.9em" }}>{run.id}</Box></DialogTitle>

      <DialogContent>
        <Box sx={{ mb: 2 }}>
          <Typography variant="body2" color="text.secondary">
            Status: <strong>{run.status}</strong>
          </Typography>
          <Typography variant="body2" color="text.secondary">
            {formatInZone(run.startedAt, timeZone)} – {formatInZone(run.finishedAt, timeZone)}
          </Typography>
        </Box>

        {stopMessage && (
          <Typography variant="body2" color="success.main" sx={{ mb: 2 }}>
            {stopMessage}
          </Typography>
        )}
        {stopError && (
          <Alert severity="error" sx={{ mb: 2 }}>
            {stopError}
          </Alert>
        )}

        {hasBreakdown ? (
          <Table size="small" sx={{ mt: 2 }}>
            <TableHead>
              <TableRow>
                <TableCell>Job board</TableCell>
                <TableCell align="right">Postings seen</TableCell>
                <TableCell align="right">For review</TableCell>
                <TableCell align="right">Rejected</TableCell>
              </TableRow>
            </TableHead>
            <TableBody>
              {run.boardBreakdown.map((entry: BoardBreakdown, idx: number) => (
                <TableRow key={`${entry.board}-${idx}`}>
                  <TableCell>{entry.board}</TableCell>
                  <TableCell align="right">{entry.postingsSeen}</TableCell>
                  <TableCell align="right">{entry.forReview}</TableCell>
                  <TableCell align="right">{entry.rejected}</TableCell>
                </TableRow>
              ))}
              <TableRow sx={{ backgroundColor: "var(--ground)" }}>
                <TableCell sx={{ fontWeight: "bold", borderTop: "2px solid var(--line)" }}>Total</TableCell>
                <TableCell align="right" sx={{ fontWeight: "bold", borderTop: "2px solid var(--line)" }}>
                  {totals.postingsSeen}
                </TableCell>
                <TableCell align="right" sx={{ fontWeight: "bold", borderTop: "2px solid var(--line)" }}>
                  {totals.forReview}
                </TableCell>
                <TableCell align="right" sx={{ fontWeight: "bold", borderTop: "2px solid var(--line)" }}>
                  {totals.rejected}
                </TableCell>
              </TableRow>
            </TableBody>
          </Table>
        ) : (
          <Typography color="text.secondary" sx={{ mt: 2 }}>
            No screenings recorded.
          </Typography>
        )}
      </DialogContent>

      <DialogActions>
        {run.status === "running" && <StopRunButton runId={run.id} stopping={stopping} onClick={handleStop} />}
        <Button onClick={onClose}>Close</Button>
      </DialogActions>
    </Dialog>
  );
}
