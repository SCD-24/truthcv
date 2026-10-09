import type { ScreeningRecord } from "../api/types";

/** Rejection reason keys (the agent's failing criterion) mapped to operator-facing labels. Insertion order is the display order. */
export const REJECTION_CATEGORY_LABELS: Record<string, string> = {
  remote_model: "Remote model",
  working_language: "Working language",
  salary_floor: "Salary",
  employment_country: "Employment country",
  rejected_role_types: "Role type",
  eor_allowed: "EOR / PEO",
  role_fit: "Role fit",
  posting_age: "Posting too old",
  cooldown: "Cooldown",
  other: "Other",
  none: "No reason given",
};

/** Category key for a record: empty/missing -> 'none', a known key -> itself, anything else -> 'other'. */
export function categoryOf(record: Pick<ScreeningRecord, "failingCriterion">): string {
  const value = record.failingCriterion;
  if (!value) return "none";
  return Object.prototype.hasOwnProperty.call(REJECTION_CATEGORY_LABELS, value) ? value : "other";
}

/** Display label for a category key; unknown keys fall back to the key itself. */
export function categoryLabel(key: string): string {
  return Object.prototype.hasOwnProperty.call(REJECTION_CATEGORY_LABELS, key)
    ? REJECTION_CATEGORY_LABELS[key]
    : key;
}

/** Row counts per category, in label order, only categories that are present. */
export function countByCategory(
  rows: Pick<ScreeningRecord, "failingCriterion">[],
): { key: string; count: number }[] {
  const counts = new Map<string, number>();
  for (const r of rows) {
    const k = categoryOf(r);
    counts.set(k, (counts.get(k) ?? 0) + 1);
  }
  return Object.keys(REJECTION_CATEGORY_LABELS)
    .filter((k) => counts.has(k))
    .map((key) => ({ key, count: counts.get(key) as number }));
}

/** Rows in the given category, or all rows when key is 'all'. */
export function filterByCategory<T extends Pick<ScreeningRecord, "failingCriterion">>(
  rows: T[],
  key: string,
): T[] {
  return key === "all" ? rows : rows.filter((r) => categoryOf(r) === key);
}
