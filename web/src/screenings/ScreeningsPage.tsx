import { useEffect, useState } from "react";
import type { KeyboardEvent } from "react";
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
import TextField from "@mui/material/TextField";
import FormControlLabel from "@mui/material/FormControlLabel";
import Checkbox from "@mui/material/Checkbox";
import { deleteScreening, listScreenings, setScreeningRole } from "../api/client";
import type { ScreeningRecord } from "../api/types";
import { isCooldownActive } from "../settings/cooldown";
import { lastAgentActivity } from "../settings/agentActivity";

/** How a cooldown reads in the table: the active/expired/none label the chip
 * carries, kept separate from the pure isCooldownActive predicate. */
function cooldownLabel(record: ScreeningRecord, active: boolean): string {
  if (active) return `Until ${record.cooldownExpires}`;
  return record.cooldownExpires ? "Expired" : "No cooldown";
}

export { cooldownLabel };

/** Human label for a screening_blocker value, for the badge and the filter. */
const BLOCKER_LABELS: Record<string, string> = {
  login_required: "Login required",
  unreadable: "Unreadable",
  not_found: "Not found",
  expired: "Expired listing",
};

function blockerLabel(blocker: string): string {
  return BLOCKER_LABELS[blocker] ?? blocker;
}

export { blockerLabel };

/** A role a user typed vs the role as last committed — if they match, a
 * commit is a no-op that must not fire a request. */
export function roleUnchanged(draft: string, stored: string): boolean {
  return draft === stored;
}

/** The Role cell, editable in place: click to open a text field seeded with
 * the current role, commit on Enter or blur, cancel on Escape. The server's
 * (possibly normalized) response is what gets shown — never the typed
 * string — and a rejected commit stays in edit mode with the server's
 * message, leaving the stored role untouched. */
function RoleCell({
  record,
  busy,
  onSave,
}: {
  record: ScreeningRecord;
  busy: boolean;
  onSave: (id: string, role: string) => Promise<void>;
}) {
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState(record.role);
  const [error, setError] = useState("");

  function startEdit() {
    setDraft(record.role);
    setError("");
    setEditing(true);
  }

  function cancel() {
    setDraft(record.role);
    setError("");
    setEditing(false);
  }

  async function commit() {
    if (!editing) return;
    if (roleUnchanged(draft, record.role)) {
      setEditing(false);
      return;
    }
    setError("");
    try {
      await onSave(record.id, draft);
      setEditing(false);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Couldn't save the role.");
    }
  }

  function onKeyDown(e: KeyboardEvent<HTMLInputElement>) {
    if (e.key === "Enter") commit();
    else if (e.key === "Escape") cancel();
  }

  if (!editing) {
    return (
      <TableCell onClick={startEdit} sx={{ cursor: "pointer" }}>
        {record.role || "—"}
      </TableCell>
    );
  }

  return (
    <TableCell>
      <Stack spacing={0.5}>
        <TextField
          size="small"
          autoFocus
          value={draft}
          disabled={busy}
          onChange={(e) => setDraft(e.target.value)}
          onKeyDown={onKeyDown}
          onBlur={commit}
        />
        {error ? (
          <Typography variant="caption" color="error">
            {error}
          </Typography>
        ) : null}
      </Stack>
    </TableCell>
  );
}

/** Human wording for WHY a company is blocked, so the user can tell which
 * setting governs it: a blocklist entry vs a same-role vs a same-company
 * cooldown window. Mirrors screening/cooldown.py's CooldownStatus.window. */
export function cooldownBlockLabel(window: "same_role" | "same_company" | null): string {
  if (window === "same_role") return "blocked: already applied to this role";
  if (window === "same_company") return "blocked: recently applied to this company";
  return "blocked: on the blocklist";
}

/** One rejected-target row: company/reason, role, verdict, why it failed, its
 * cooldown state, and a delete control to un-block it. */
function ScreeningRow({
  record,
  deleting,
  onDelete,
  savingRole,
  onSaveRole,
}: {
  record: ScreeningRecord;
  deleting: boolean;
  onDelete: (id: string) => void;
  savingRole: boolean;
  onSaveRole: (id: string, role: string) => Promise<void>;
}) {
  const active = isCooldownActive(record.cooldownExpires);
  return (
    <TableRow>
      <TableCell>
        <Tooltip title={record.reason || "No reason recorded."}>
          <Typography variant="body2">{record.company || "—"}</Typography>
        </Tooltip>
      </TableCell>
      <RoleCell record={record} busy={savingRole} onSave={onSaveRole} />
      <TableCell>
        {record.screeningBlocker ? (
          <Chip
            size="small"
            variant="outlined"
            color="warning"
            label={`Couldn't read: ${blockerLabel(record.screeningBlocker)}`}
          />
        ) : (
          record.verdict || "—"
        )}
      </TableCell>
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
  const [savingRoleId, setSavingRoleId] = useState<string | null>(null);
  const [blockedOnly, setBlockedOnly] = useState(false);

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

  /** Save a corrected role and replace the record with the server's
   * (normalized) response — errors propagate for RoleCell to show inline. */
  async function handleSaveRole(id: string, role: string) {
    setSavingRoleId(id);
    try {
      const updated = await setScreeningRole(id, role);
      setScreenings((prev) => prev.map((r) => (r.id === id ? updated : r)));
    } finally {
      setSavingRoleId(null);
    }
  }

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
  const visibleScreenings = blockedOnly
    ? screenings.filter((r) => r.screeningBlocker)
    : screenings;

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
          <FormControlLabel
            control={
              <Checkbox
                size="small"
                checked={blockedOnly}
                onChange={(e) => setBlockedOnly(e.target.checked)}
              />
            }
            label="Show only postings the agent couldn't read"
          />
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
              {visibleScreenings.map((record) => (
                <ScreeningRow
                  key={record.id}
                  record={record}
                  deleting={deletingId === record.id}
                  onDelete={handleDelete}
                  savingRole={savingRoleId === record.id}
                  onSaveRole={handleSaveRole}
                />
              ))}
            </TableBody>
          </Table>
        </Stack>
      )}
    </Box>
  );
}
