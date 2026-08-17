import type { Application } from "../api/types";

export type SortDirection = "asc" | "desc";
export type ColumnDef = {
  label: string;
  sortable: boolean;
  compare?: (a: Application, b: Application) => number;
};

// Order applications by status; lower index sorts first. Unlisted/unset
// statuses (e.g. "") fall to the bottom.
const STATUS_ORDER = [
  "Offer",
  "Interviewing",
  "Waiting",
  "Applied",
  "Draft",
  "Rejected",
] as const;

export function statusRank(status: string): number {
  const i = STATUS_ORDER.indexOf(status as (typeof STATUS_ORDER)[number]);
  return i === -1 ? STATUS_ORDER.length : i;
}

const text = (get: (a: Application) => string | null | undefined) =>
  (a: Application, b: Application) => {
    const av = (get(a) ?? "").trim(), bv = (get(b) ?? "").trim();
    if (!av && !bv) return 0;
    if (!av) return 1; // blanks last in ascending; desc flips (accepted).
    if (!bv) return -1;
    return av.toLowerCase().localeCompare(bv.toLowerCase());
  };
const bool = (get: (a: Application) => boolean) =>
  (a: Application, b: Application) => Number(get(b)) - Number(get(a)); // yes-first asc
const presence = (get: (a: Application) => unknown) =>
  (a: Application, b: Application) => Number(Boolean(get(b))) - Number(Boolean(get(a)));

const host = (url: string | null | undefined): string => {
  if (!url) return "";
  try {
    return new URL(url).host;
  } catch {
    return url;
  }
};

export const COLUMN_DEFS: ColumnDef[] = [
  { label: "Company", sortable: true, compare: text((a) => a.company) },
  { label: "Date", sortable: true, compare: text((a) => a.applicationDate) }, // ISO strings: lexicographic = chronological
  { label: "Website", sortable: true, compare: text((a) => host(a.website)) },
  { label: "Application URL", sortable: true, compare: presence((a) => a.applicationUrl) },
  { label: "Submitted", sortable: true, compare: bool((a) => a.submitted) },
  { label: "Submission Type", sortable: true, compare: text((a) => a.submissionType) },
  { label: "Status", sortable: true, compare: (a, b) => statusRank(a.status) - statusRank(b.status) },
  { label: "Reached Out", sortable: true, compare: bool((a) => a.reachedOut) },
  { label: "To Who", sortable: true, compare: text((a) => a.toWho) },
  { label: "Response Received", sortable: true, compare: bool((a) => a.responseReceived) },
  { label: "Method", sortable: true, compare: text((a) => a.method) },
  { label: "Notes", sortable: true, compare: text((a) => a.notes) },
  { label: "Posting", sortable: true, compare: presence((a) => a.posting) },
  { label: "Documents", sortable: true, compare: presence((a) => a.cvDocument ?? a.coverLetterDocument) },
  { label: "", sortable: false },
];

export function defaultCompare(a: Application, b: Application): number {
  return statusRank(a.status) - statusRank(b.status);
}

export function compareApplications(
  a: Application,
  b: Application,
  col: ColumnDef | null,
  dir: SortDirection,
): number {
  if (!col?.compare) return defaultCompare(a, b);
  const r = col.compare(a, b);
  return dir === "desc" ? -r : r;
}
