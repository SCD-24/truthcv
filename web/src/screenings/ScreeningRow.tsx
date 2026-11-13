import IconButton from "@mui/material/IconButton";
import DeleteOutlineIcon from "@mui/icons-material/DeleteOutlined";
import Typography from "@mui/material/Typography";
import TableCell from "@mui/material/TableCell";
import TableRow from "@mui/material/TableRow";
import Chip from "@mui/material/Chip";
import Tooltip from "@mui/material/Tooltip";
import type { ScreeningLedgerItem } from "../api/types";
import { isCooldownActive } from "../settings/cooldown";
import { RoleCell } from "./RoleCell";

/** How a cooldown reads in the table: the active/expired/none label the chip
 * carries, kept separate from the pure isCooldownActive predicate. */
export function cooldownLabel(record: ScreeningLedgerItem, active: boolean): string {
  if (active) return `Until ${record.cooldownExpires}`;
  return record.cooldownExpires ? "Expired" : "No cooldown";
}

/** Human label for a screening_blocker value, for the badge and the filter. */
const BLOCKER_LABELS: Record<string, string> = {
  login_required: "Login required",
  unreadable: "Unreadable",
  not_found: "Not found",
  expired: "Expired listing",
};

export function blockerLabel(blocker: string): string {
  return BLOCKER_LABELS[blocker] ?? blocker;
}

/** The company name, with the recorded reason as its tooltip. */
function CompanyCell({ record }: { record: ScreeningLedgerItem }) {
  return (
    <TableCell>
      <Tooltip title={record.reason || "No reason recorded."}>
        <Typography variant="body2">{record.company || "—"}</Typography>
      </Tooltip>
    </TableCell>
  );
}

/** The verdict, or a warning chip naming why the posting couldn't be read. */
function VerdictCell({ record }: { record: ScreeningLedgerItem }) {
  return (
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
  );
}

/** The cooldown chip: warning-coloured while the cooldown is active. */
function CooldownCell({ record }: { record: ScreeningLedgerItem }) {
  const active = isCooldownActive(record.cooldownExpires);
  return (
    <TableCell>
      <Chip
        size="small"
        variant="outlined"
        color={active ? "warning" : "default"}
        label={cooldownLabel(record, active)}
      />
    </TableCell>
  );
}

/** The delete control that un-blocks a target. */
function DeleteCell({
  record,
  deleting,
  onDelete,
}: {
  record: ScreeningLedgerItem;
  deleting: boolean;
  onDelete: (id: string) => void;
}) {
  return (
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
  );
}

/** One rejected-target row: company/reason, role, verdict, why it failed, its
 * cooldown state, and a delete control to un-block it. */
export function ScreeningRow({
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
  return (
    <TableRow>
      <CompanyCell record={record} />
      <RoleCell record={record} busy={savingRole} onSave={onSaveRole} />
      <VerdictCell record={record} />
      <TableCell>{record.failingCriterion || "—"}</TableCell>
      <CooldownCell record={record} />
      <DeleteCell record={record} deleting={deleting} onDelete={onDelete} />
    </TableRow>
  );
}
