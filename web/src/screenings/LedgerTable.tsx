import type { ReactNode } from "react";
import Stack from "@mui/material/Stack";
import Typography from "@mui/material/Typography";
import Table from "@mui/material/Table";
import TableBody from "@mui/material/TableBody";
import TableCell from "@mui/material/TableCell";
import TableHead from "@mui/material/TableHead";
import TableRow from "@mui/material/TableRow";
import FormControlLabel from "@mui/material/FormControlLabel";
import Checkbox from "@mui/material/Checkbox";
import TablePagination from "@mui/material/TablePagination";
import type { ScreeningLedgerItem, ScreeningLedgerPage } from "../api/types";
import { LEDGER_PAGE_SIZE } from "./useLedgerPage";
import type { LedgerView } from "./useLedgerPage";

/** The ledger's column headings, left of the Delete column. */
const LEDGER_COLUMNS = ["Company", "Role", "Verdict", "Failing criterion", "Cooldown"];

/** Last-activity line (when known) and the blocked-only filter checkbox. */
function LedgerToolbar({ view, lastActivity }: { view: LedgerView; lastActivity: string | null }) {
  const lastLabel = lastActivity ? new Date(lastActivity).toLocaleDateString() : null;
  return (
    <>
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
    </>
  );
}

/** The ledger's header row and one body row per record. */
function LedgerGrid({
  items,
  row,
}: {
  items: ScreeningLedgerItem[];
  row: (record: ScreeningLedgerItem) => ReactNode;
}) {
  return (
    <Table size="small">
      <TableHead>
        <TableRow>
          {LEDGER_COLUMNS.map((c) => (
            <TableCell key={c}>{c}</TableCell>
          ))}
          <TableCell align="right">Delete</TableCell>
        </TableRow>
      </TableHead>
      <TableBody>{items.map(row)}</TableBody>
    </Table>
  );
}

/** The loaded ledger: last activity, the blocked-only filter, one page of
 * rows and the page controls. */
export function LedgerTable({
  view,
  data,
  row,
}: {
  view: LedgerView;
  data: ScreeningLedgerPage;
  row: (record: ScreeningLedgerItem) => ReactNode;
}) {
  return (
    <Stack spacing={2}>
      <LedgerToolbar view={view} lastActivity={data.lastActivity} />
      <LedgerGrid items={data.items} row={row} />
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
