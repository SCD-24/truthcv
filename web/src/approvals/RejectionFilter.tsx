import MenuItem from "@mui/material/MenuItem";
import TextField from "@mui/material/TextField";
import { categoryLabel } from "./rejectionCategories";
import type { RejectionCategoryCount } from "../api/types";

/** Rejection-reason filter for the Rejected tab: 'All (N)' plus one option per
 * category the server reports, each with its count. */
export function RejectionFilter({
  categories,
  value,
  onChange,
}: {
  categories: RejectionCategoryCount[];
  value: string;
  onChange: (key: string) => void;
}) {
  const all = categories.reduce((sum, c) => sum + c.count, 0);
  return (
    <TextField
      select
      size="small"
      label="Rejection reason"
      value={value}
      onChange={(e) => onChange(e.target.value)}
      sx={{ minWidth: 220 }}
    >
      <MenuItem value="all">{`All (${all})`}</MenuItem>
      {categories.map(({ key, count }) => (
        <MenuItem key={key} value={key}>{`${categoryLabel(key)} (${count})`}</MenuItem>
      ))}
    </TextField>
  );
}
