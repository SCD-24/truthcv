import type { ApplicationSortKey } from "../api/types";

export type SortDirection = "asc" | "desc";
export type ColumnDef = {
  label: string;
  sortable: boolean;
  /** The server sort key this column orders by (GET /api/applications/page).
   * Sorting happens server-side so it holds across pages; the comparator
   * semantics live in applications/sorting.py. */
  sortKey?: ApplicationSortKey;
};

// The Website/URL/Posting/Documents/Filled-form columns were folded into the
// links line under the company name (ApplicationLinks), so they are no longer
// table columns. Their server sort keys still exist on the API.
export const COLUMN_DEFS: ColumnDef[] = [
  { label: "Company", sortable: true, sortKey: "company" },
  { label: "Date", sortable: true, sortKey: "date" },
  { label: "Submitted", sortable: true, sortKey: "submitted" },
  { label: "Type", sortable: true, sortKey: "type" },
  { label: "Status", sortable: true, sortKey: "status" },
  { label: "Reached Out", sortable: true, sortKey: "reachedOut" },
  { label: "To Who", sortable: true, sortKey: "toWho" },
  { label: "Response", sortable: true, sortKey: "response" },
  { label: "Method", sortable: true, sortKey: "method" },
  { label: "Notes", sortable: true, sortKey: "notes" },
  { label: "", sortable: false },
];

/** The column the table sorts by on load, with {@link DEFAULT_SORT_DIRECTION}:
 * most recently applied first, which is what an operator scanning this page is
 * almost always looking for. */
export const DEFAULT_SORT_COLUMN: ColumnDef =
  COLUMN_DEFS.find((c) => c.label === "Date") ?? COLUMN_DEFS[0];

export const DEFAULT_SORT_DIRECTION: SortDirection = "desc";
