import MenuItem from "@mui/material/MenuItem";
import TextField from "@mui/material/TextField";
import { categoryLabel, countByCategory } from "./rejectionCategories";
import type { ScreeningRecord } from "../api/types";

/** Rejection-reason filter for the Rejected tab: 'All (N)' plus one option per
 * category present, each with its count. */
export function RejectionFilter({
  rows,
  value,
  onChange,
}: {
  rows: Pick<ScreeningRecord, "failingCriterion">[];
  value: string;
  onChange: (key: string) => void;
}) {
  return (
    <TextField
      select
      size="small"
      label="Rejection reason"
      value={value}
      onChange={(e) => onChange(e.target.value)}
      sx={{ minWidth: 220 }}
    >
      <MenuItem value="all">{`All (${rows.length})`}</MenuItem>
      {countByCategory(rows).map(({ key, count }) => (
        <MenuItem key={key} value={key}>{`${categoryLabel(key)} (${count})`}</MenuItem>
      ))}
    </TextField>
  );
}
