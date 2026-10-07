import { useState } from "react";
import { Table, TableHead, TableBody, TableRow, TableCell, Tooltip, Collapse, Alert, Box } from "@mui/material";
import type { BoardBreakdown, RunRecord } from "../api/types";
import { FUNNEL_COLUMNS, formatCount, funnelTotals, mismatchMessage, sourceLabel } from "./runFunnel";
import { RunSourceUrls } from "./RunSourceUrls";

const NUM_SX = { fontVariantNumeric: "tabular-nums" } as const;
const TOTAL_SX = { fontWeight: "bold", borderTop: "2px solid var(--line)", ...NUM_SX } as const;
const BUTTON_SX = {
  font: "inherit",
  color: "inherit",
  background: "none",
  border: 0,
  padding: 0,
  cursor: "pointer",
  textAlign: "left",
  "&:focus-visible": { outline: "2px solid currentColor", outlineOffset: 2 },
} as const;

function HeaderRow() {
  return (
    <TableRow>
      <TableCell>Source</TableCell>
      {FUNNEL_COLUMNS.map((c) => (
        <TableCell key={c.key} align="right">
          <Tooltip title={c.tooltip}>
            <span>{c.label}</span>
          </Tooltip>
        </TableCell>
      ))}
    </TableRow>
  );
}

interface SourceRowProps {
  run: RunRecord;
  row: BoardBreakdown;
  expanded: boolean;
  onToggle: () => void;
}

function SourceRow({ run, row, expanded, onToggle }: SourceRowProps) {
  const label = sourceLabel(row);
  const expandable = row.postingsSeen !== null;
  return (
    <>
      <TableRow onClick={expandable ? onToggle : undefined} sx={expandable ? { cursor: "pointer" } : undefined}>
        <TableCell>
          {expandable ? (
            // Click bubbles to the row, which toggles; no handler here avoids a double toggle.
            <Box component="button" type="button" aria-expanded={expanded} sx={BUTTON_SX}>
              {label}
            </Box>
          ) : (
            label
          )}
        </TableCell>
        {FUNNEL_COLUMNS.map((c) => (
          <TableCell key={c.key} align="right" sx={NUM_SX}>
            {formatCount(row[c.key])}
          </TableCell>
        ))}
      </TableRow>
      {expandable && (
        <TableRow>
          <TableCell colSpan={FUNNEL_COLUMNS.length + 1} sx={{ py: 0, borderBottom: expanded ? undefined : 0 }}>
            <Collapse in={expanded} unmountOnExit>
              <RunSourceUrls key={`${run.id}|${row.board}|${row.channel}`} runId={run.id} row={row} truncated={run.urlLedgerTruncated} />
            </Collapse>
          </TableCell>
        </TableRow>
      )}
    </>
  );
}


function TotalRow({ run }: { run: RunRecord }) {
  const totals = funnelTotals(run);
  return (
    <TableRow sx={{ backgroundColor: "var(--ground)" }}>
      <TableCell sx={{ fontWeight: "bold", borderTop: "2px solid var(--line)" }}>Total</TableCell>
      {FUNNEL_COLUMNS.map((c) => (
        <TableCell key={c.key} align="right" sx={TOTAL_SX}>
          {formatCount(totals[c.key])}
        </TableCell>
      ))}
    </TableRow>
  );
}

/** Per-source funnel table with expandable URL panels and a Total row. */
export function RunFunnelTable({ run }: { run: RunRecord }) {
  const [openKey, setOpenKey] = useState<string | null>(null);
  const warning = mismatchMessage(run);
  return (
    <>
      {warning && (
        <Alert severity="warning" sx={{ mt: 2 }}>
          {warning}
        </Alert>
      )}
      <Table size="small" sx={{ mt: 2 }}>
        <TableHead>
          <HeaderRow />
        </TableHead>
        <TableBody>
          {run.boardBreakdown.map((row, idx) => {
            const key = `${row.channel}|${row.board}|${idx}`;
            const toggle = () => setOpenKey(openKey === key ? null : key);
            return <SourceRow key={key} run={run} row={row} expanded={openKey === key} onToggle={toggle} />;
          })}
          <TotalRow run={run} />
        </TableBody>
      </Table>
    </>
  );
}
