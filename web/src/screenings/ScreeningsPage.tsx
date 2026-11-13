import type { ReactNode } from "react";
import Box from "@mui/material/Box";
import Stack from "@mui/material/Stack";
import Alert from "@mui/material/Alert";
import Typography from "@mui/material/Typography";
import CircularProgress from "@mui/material/CircularProgress";
import type { ScreeningLedgerItem } from "../api/types";
import { LedgerTable } from "./LedgerTable";
import { ScreeningRow } from "./ScreeningRow";
import { useLedgerPage } from "./useLedgerPage";
import type { LedgerView } from "./useLedgerPage";
import { useDeleteRecord, useSaveRole } from "./useScreeningActions";

export { cooldownLabel, blockerLabel } from "./ScreeningRow";
export { roleUnchanged } from "./RoleCell";

/** Human wording for WHY a company is blocked, so the user can tell which
 * setting governs it: a blocklist entry vs a same-role vs a same-company
 * cooldown window. Mirrors truthcv/domain/screening/cooldown.py's CooldownStatus.window. */
export function cooldownBlockLabel(window: "same_role" | "same_company" | null): string {
  if (window === "same_role") return "blocked: already applied to this role";
  if (window === "same_company") return "blocked: recently applied to this company";
  return "blocked: on the blocklist";
}

/** The page's eyebrow and title. */
function PageHeader() {
  return (
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
  );
}

/** The page-level error alert, or nothing when there is no error. */
function ErrorBanner({ error }: { error: string | null }) {
  return error ? (
    <Alert severity="error" sx={{ mb: 2 }}>
      {error}
    </Alert>
  ) : null;
}

/** The ledger area: loading spinner, empty message, or the loaded table. */
function LedgerBody({
  view,
  row,
}: {
  view: LedgerView;
  row: (record: ScreeningLedgerItem) => ReactNode;
}) {
  const { data } = view;
  if (!data && !view.error) {
    return (
      <Stack direction="row" spacing={2} sx={{ py: 6, justifyContent: "center" }}>
        <CircularProgress size={20} sx={{ color: "var(--attest)" }} />
        <Typography color="text.secondary">Loading screenings…</Typography>
      </Stack>
    );
  }
  if (!data || (data.total === 0 && !view.blockedOnly)) {
    return (
      <Typography color="text.secondary" sx={{ py: 6, textAlign: "center" }}>
        The agent hasn't recorded any activity yet.
      </Typography>
    );
  }
  return <LedgerTable view={view} data={data} row={row} />;
}

/**
 * The Screenings page — the agent's rejection & cooldown ledger, on its own
 * page (mirroring AnalyticsPage). Loads one server page of the ledger via
 * `listScreeningLedgerPage()` with loading/error/empty states, and lets the
 * operator delete a record to un-block a target immediately.
 */
export function ScreeningsPage() {
  const view = useLedgerPage();
  const save = useSaveRole(view.patchItem);
  const del = useDeleteRecord(view.refetch);
  const row = (record: ScreeningLedgerItem) => (
    <ScreeningRow
      key={record.id}
      record={record}
      deleting={del.deletingId === record.id}
      onDelete={del.handleDelete}
      savingRole={save.savingRoleId === record.id}
      onSaveRole={save.handleSaveRole}
    />
  );

  return (
    <Box className="screenings-page" aria-labelledby="screenings-title">
      <PageHeader />
      <ErrorBanner error={del.actionError ?? view.error} />
      <LedgerBody view={view} row={row} />
    </Box>
  );
}
