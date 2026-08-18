import { useEffect, useState } from "react";
import Box from "@mui/material/Box";
import Stack from "@mui/material/Stack";
import Button from "@mui/material/Button";
import IconButton from "@mui/material/IconButton";
import DeleteOutlineIcon from "@mui/icons-material/DeleteOutlined";
import ArrowBackIcon from "@mui/icons-material/ArrowBack";
import Alert from "@mui/material/Alert";
import Typography from "@mui/material/Typography";
import CircularProgress from "@mui/material/CircularProgress";
import Table from "@mui/material/Table";
import TableBody from "@mui/material/TableBody";
import TableCell from "@mui/material/TableCell";
import TableHead from "@mui/material/TableHead";
import TableRow from "@mui/material/TableRow";
import Chip from "@mui/material/Chip";
import Tooltip from "@mui/material/Tooltip";
import { deleteScreening, listScreenings } from "../api/client";
import type { ScreeningRecord } from "../api/types";
import { isCooldownActive } from "../settings/cooldown";
import { lastAgentActivity } from "../settings/agentActivity";

/** How a cooldown reads in the table: the active/expired/none label the chip
 * carries, kept separate from the pure isCooldownActive predicate. */
function cooldownLabel(record: ScreeningRecord, active: boolean): string {
  if (active) return `Until ${record.cooldownExpires}`;
  return record.cooldownExpires ? "Expired" : "No cooldown";
}

/** One rejected-target row: company/reason, role, verdict, why it failed, its
 * cooldown state, and a delete control to un-block it. */
function ScreeningRow({
  record,
  deleting,
  onDelete,
}: {
  record: ScreeningRecord;
  deleting: boolean;
  onDelete: (id: string) => void;
}) {
  const active = isCooldownActive(record.cooldownExpires);
  return (
    <TableRow>
      <TableCell>
        <Tooltip title={record.reason || "No reason recorded."}>
          <Typography variant="body2">{record.company || "—"}</Typography>
        </Tooltip>
      </TableCell>
      <TableCell>{record.role || "—"}</TableCell>
      <TableCell>{record.verdict || "—"}</TableCell>
      <TableCell>{record.failingCriterion || "—"}</TableCell>
      <TableCell>
        <Chip
          size="small"
          variant="outlined"
          color={active ? "warning" : "default"}
          label={cooldownLabel(record, active)}
        />
      </TableCell>
      <TableCell align="right">
        <IconButton
          aria-label={`Delete screening record for ${record.company || "this target"}`}
          onClick={() => onDelete(record.id)}
          disabled={deleting}
          size="small"
        >
          <DeleteOutlineIcon fontSize="small" />
        </IconButton>
      </TableCell>
    </TableRow>
  );
}

/**
 * The Screenings page — the agent's rejection & cooldown ledger, on its own
 * page (mirroring AnalyticsPage). Loads `ScreeningRecord[]` via
 * `listScreenings()` with loading/error/empty states, and lets the operator
 * delete a record to un-block a target immediately. `onBack` returns to the
 * wizard step the user left.
 */
export function ScreeningsPage({ onBack }: { onBack: () => void }) {
  const [screenings, setScreenings] = useState<ScreeningRecord[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [deletingId, setDeletingId] = useState<string | null>(null);

  useEffect(() => {
    let alive = true;
    listScreenings()
      .then((records) => {
        if (alive) setScreenings(records);
      })
      .catch((e) => {
        if (alive) {
          setError(e instanceof Error ? e.message : "Couldn't load screenings.");
        }
      })
      .finally(() => {
        if (alive) setLoading(false);
      });
    return () => {
      alive = false;
    };
  }, []);

  /** Delete a screening record and drop it from the loaded list. */
  async function handleDelete(id: string) {
    setDeletingId(id);
    setError(null);
    try {
      await deleteScreening(id);
      setScreenings((prev) => prev.filter((r) => r.id !== id));
    } catch (e) {
      setError(e instanceof Error ? e.message : "Couldn't delete the screening record.");
    } finally {
      setDeletingId(null);
    }
  }

  const last = lastAgentActivity(screenings);
  const lastLabel = last ? new Date(last).toLocaleDateString() : null;

  return (
    <Box className="screenings-page" aria-labelledby="screenings-title">
      <Stack
        direction="row"
        sx={{ mb: 3, alignItems: "flex-start", justifyContent: "space-between", gap: 2 }}
      >
        <Box>
          <Typography variant="overline" className="screenings__eyebrow" sx={{ display: "block" }}>
            Screening ledger
          </Typography>
          <Typography id="screenings-title" variant="h4" component="h1">
            Screenings
          </Typography>
        </Box>
        <Button variant="text" startIcon={<ArrowBackIcon />} onClick={onBack}>
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
          <Typography color="text.secondary">Loading screenings…</Typography>
        </Stack>
      ) : screenings.length === 0 ? (
        <Typography color="text.secondary" sx={{ py: 6, textAlign: "center" }}>
          The agent hasn't recorded any activity yet.
        </Typography>
      ) : (
        <Stack spacing={2}>
          {lastLabel && (
            <Typography variant="body2" color="text.secondary">
              Last recorded activity: {lastLabel}
            </Typography>
          )}
          <Table size="small">
            <TableHead>
              <TableRow>
                <TableCell>Company</TableCell>
                <TableCell>Role</TableCell>
                <TableCell>Verdict</TableCell>
                <TableCell>Failing criterion</TableCell>
                <TableCell>Cooldown</TableCell>
                <TableCell align="right">Delete</TableCell>
              </TableRow>
            </TableHead>
            <TableBody>
              {screenings.map((record) => (
                <ScreeningRow
                  key={record.id}
                  record={record}
                  deleting={deletingId === record.id}
                  onDelete={handleDelete}
                />
              ))}
            </TableBody>
          </Table>
        </Stack>
      )}
    </Box>
  );
}
