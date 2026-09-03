import type { ApplicationSortKey } from "../api/types";

export type SortDirection = "asc" | "desc";
export type ColumnDef = {
  label: string;
  sortable: boolean;
  sortKey?: ApplicationSortKey;
};

export const COLUMN_DEFS: ColumnDef[] = [
  { label: "Company", sortable: true, sortKey: "company" },
  { label: "Date", sortable: true, sortKey: "date" },
  { label: "Website", sortable: true, sortKey: "website" },
  { label: "URL", sortable: true, sortKey: "url" },
  { label: "Submitted", sortable: true, sortKey: "submitted" },
  { label: "Type", sortable: true, sortKey: "type" },
  { label: "Status", sortable: true, sortKey: "status" },
  { label: "Reached Out", sortable: true, sortKey: "reachedOut" },
  { label: "To Who", sortable: true, sortKey: "toWho" },
  { label: "Response", sortable: true, sortKey: "response" },
  { label: "Method", sortable: true, sortKey: "method" },
  { label: "Notes", sortable: true, sortKey: "notes" },
  { label: "Posting", sortable: true, sortKey: "posting" },
  { label: "Documents", sortable: true, sortKey: "documents" },
  { label: "Filled form", sortable: true, sortKey: "filledForm" },
  { label: "", sortable: false },
];

/** The column the table sorts by on load, with {@link DEFAULT_SORT_DIRECTION}:
 * most recently applied first, which is what an operator scanning this page is
 * almost always looking for. */
export const DEFAULT_SORT_COLUMN: ColumnDef =
  COLUMN_DEFS.find((c) => c.label === "Date") ?? COLUMN_DEFS[0];

export const DEFAULT_SORT_DIRECTION: SortDirection = "desc";
