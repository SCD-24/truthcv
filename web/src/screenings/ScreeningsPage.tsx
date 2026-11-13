import { useEffect, useState } from "react";
import type { KeyboardEvent, ReactNode } from "react";
import Box from "@mui/material/Box";
import Stack from "@mui/material/Stack";
import IconButton from "@mui/material/IconButton";
import DeleteOutlineIcon from "@mui/icons-material/DeleteOutlined";
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
import TablePagination from "@mui/material/TablePagination";
import { deleteScreening, listScreeningLedgerPage, setScreeningRole } from "../api/client";
import type { ScreeningLedgerItem, ScreeningLedgerPage } from "../api/types";
import { isCooldownActive } from "../settings/cooldown";

/** How a cooldown reads in the table: the active/expired/none label the chip
 * carries, kept separate from the pure isCooldownActive predicate. */
function cooldownLabel(record: ScreeningLedgerItem, active: boolean): string {
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
  record: ScreeningLedgerItem;
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
 * cooldown window. Mirrors truthcv/domain/screening/cooldown.py's CooldownStatus.window. */
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
  record: ScreeningLedgerItem;
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

/** Rows per ledger page, matching the other paged lists' fixed size. */
const LEDGER_PAGE_SIZE = 50;

type LedgerPos = { page: number; blockedOnly: boolean };

/** Fetch the ledger page `pos` names, again whenever `nonce` changes. Each
 * fetch supersedes the one before it, so a stale response never overwrites a
 * newer one; a page a delete emptied moves back to the last page with rows.
 * Loading is the state before the first response or error. */
function useLedgerFetch(pos: LedgerPos, nonce: number, setPos: (p: LedgerPos) => void) {
  const [data, setData] = useState<ScreeningLedgerPage | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let live = true;
    const { page, blockedOnly } = pos;
    listScreeningLedgerPage({ limit: LEDGER_PAGE_SIZE, offset: page * LEDGER_PAGE_SIZE, blockedOnly })
      .then((res) => {
        if (!live) return;
        setError(null);
        setData(res);
        const next = Math.min(page, Math.max(0, Math.ceil(res.total / LEDGER_PAGE_SIZE) - 1));
        if (next !== page) setPos({ page: next, blockedOnly });
      })
      .catch((e) => live && setError(e instanceof Error ? e.message : "Couldn't load screenings."));
    return () => {
      live = false;
    };
  }, [pos, nonce, setPos]);

  return { data, setData, error };
}

/** The ledger's server page plus its position: the page, the blocked-only
 * filter (which resets to the first page), a refetch, and an in-place patch. */
function useLedgerPage() {
  const [pos, setPos] = useState<LedgerPos>({ page: 0, blockedOnly: false });
  const [nonce, setNonce] = useState(0);
  const { setData, ...fetched } = useLedgerFetch(pos, nonce, setPos);

  /** Swap in an edited record without refetching. */
  const patchItem = (updated: ScreeningLedgerItem) =>
    setData((d) => d && { ...d, items: d.items.map((r) => (r.id === updated.id ? updated : r)) });

  return {
    ...pos,
    ...fetched,
    setPage: (page: number) => setPos((p) => ({ ...p, page })),
    setBlockedOnly: (blockedOnly: boolean) => setPos({ page: 0, blockedOnly }),
    refetch: () => setNonce((n) => n + 1),
    patchItem,
  };
}

type LedgerView = ReturnType<typeof useLedgerPage>;

/** The ledger's column headings, left of the Delete column. */
const LEDGER_COLUMNS = ["Company", "Role", "Verdict", "Failing criterion", "Cooldown"];

/** The loaded ledger: last activity, the blocked-only filter, one page of
 * rows and the page controls. */
function LedgerTable({
  view,
  data,
  row,
}: {
  view: LedgerView;
  data: ScreeningLedgerPage;
  row: (record: ScreeningLedgerItem) => ReactNode;
}) {
  const lastLabel = data.lastActivity ? new Date(data.lastActivity).toLocaleDateString() : null;
  return (
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
            checked={view.blockedOnly}
            onChange={(e) => view.setBlockedOnly(e.target.checked)}
          />
        }
        label="Show only postings the agent couldn't read"
      />
      <Table size="small">
        <TableHead>
          <TableRow>
            {LEDGER_COLUMNS.map((c) => (
              <TableCell key={c}>{c}</TableCell>
            ))}
            <TableCell align="right">Delete</TableCell>
          </TableRow>
        </TableHead>
        <TableBody>{data.items.map(row)}</TableBody>
      </Table>
      <TablePagination
        component="div"
        count={data.total}
        page={view.page}
        rowsPerPage={LEDGER_PAGE_SIZE}
        rowsPerPageOptions={[LEDGER_PAGE_SIZE]}
        onPageChange={(_, p) => view.setPage(p)}
      />
    </Stack>
  );
}

/**
 * The Screenings page — the agent's rejection & cooldown ledger, on its own
 * page (mirroring AnalyticsPage). Loads one server page of the ledger via
 * `listScreeningLedgerPage()` with loading/error/empty states, and lets the
 * operator delete a record to un-block a target immediately.
 */
export function ScreeningsPage() {
  const view = useLedgerPage();
  const [actionError, setActionError] = useState<string | null>(null);
  const [deletingId, setDeletingId] = useState<string | null>(null);
  const [savingRoleId, setSavingRoleId] = useState<string | null>(null);

  /** Save a corrected role and replace the record with the server's
   * (normalized) response — errors propagate for RoleCell to show inline. */
  async function handleSaveRole(id: string, role: string) {
    setSavingRoleId(id);
    try {
      view.patchItem(await setScreeningRole(id, role));
    } finally {
      setSavingRoleId(null);
    }
  }

  /** Delete a screening record and refetch the current page. */
  async function handleDelete(id: string) {
    setDeletingId(id);
    setActionError(null);
    try {
      await deleteScreening(id);
      view.refetch();
    } catch (e) {
      setActionError(e instanceof Error ? e.message : "Couldn't delete the screening record.");
    } finally {
      setDeletingId(null);
    }
  }

  const error = actionError ?? view.error;
  const { data } = view;
  const row = (record: ScreeningLedgerItem) => (
    <ScreeningRow
      key={record.id}
      record={record}
      deleting={deletingId === record.id}
      onDelete={handleDelete}
      savingRole={savingRoleId === record.id}
      onSaveRole={handleSaveRole}
    />
  );

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
      </Stack>

      {error && (
        <Alert severity="error" sx={{ mb: 2 }}>
          {error}
        </Alert>
      )}

      {!data && !view.error ? (
        <Stack direction="row" spacing={2} sx={{ py: 6, justifyContent: "center" }}>
          <CircularProgress size={20} sx={{ color: "var(--attest)" }} />
          <Typography color="text.secondary">Loading screenings…</Typography>
        </Stack>
      ) : !data || (data.total === 0 && !view.blockedOnly) ? (
        <Typography color="text.secondary" sx={{ py: 6, textAlign: "center" }}>
          The agent hasn't recorded any activity yet.
        </Typography>
      ) : (
        <LedgerTable view={view} data={data} row={row} />
      )}
    </Box>
  );
}
