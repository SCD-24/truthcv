import { describe, expect, it } from "vitest";
import { COLUMN_DEFS, DEFAULT_SORT_COLUMN, DEFAULT_SORT_DIRECTION } from "./sorting";

describe("sorting", () => {
  it("the table defaults to newest applications first", () => {
    expect(DEFAULT_SORT_COLUMN.label).toBe("Date");
    expect(DEFAULT_SORT_DIRECTION).toBe("desc");
  });

  it("all sortable columns have sortKeys", () => {
    for (const col of COLUMN_DEFS) {
      if (col.sortable) {
        expect(col.sortKey).toBeDefined();
        expect(typeof col.sortKey).toBe("string");
      }
    }
  });

  it("the actions column is not sortable", () => {
    expect(COLUMN_DEFS[COLUMN_DEFS.length - 1].sortable).toBe(false);
  });

  it("the Date column is the default sort column with sortKey 'date'", () => {
    expect(DEFAULT_SORT_COLUMN.label).toBe("Date");
    expect(DEFAULT_SORT_COLUMN.sortKey).toBe("date");
  });

  it("all expected columns are defined with sortKeys", () => {
    const expectedColumns = [
      { label: "Company", sortKey: "company" },
      { label: "Date", sortKey: "date" },
      { label: "Website", sortKey: "website" },
      { label: "URL", sortKey: "url" },
      { label: "Submitted", sortKey: "submitted" },
      { label: "Type", sortKey: "type" },
      { label: "Status", sortKey: "status" },
      { label: "Reached Out", sortKey: "reachedOut" },
      { label: "To Who", sortKey: "toWho" },
      { label: "Response", sortKey: "response" },
      { label: "Method", sortKey: "method" },
      { label: "Notes", sortKey: "notes" },
      { label: "Posting", sortKey: "posting" },
      { label: "Documents", sortKey: "documents" },
      { label: "Filled form", sortKey: "filledForm" },
    ];

    for (const expected of expectedColumns) {
      const col = COLUMN_DEFS.find((c) => c.label === expected.label);
      expect(col).toBeDefined();
      expect(col?.sortKey).toBe(expected.sortKey);
      expect(col?.sortable).toBe(true);
    }
  });

  it("all column labels are unique", () => {
    const labels = COLUMN_DEFS.map((c) => c.label);
    expect(new Set(labels).size).toBe(labels.length);
  });

  it("uses shortened header labels for URL, Type and Response", () => {
    expect(COLUMN_DEFS.some((c) => c.label === "URL")).toBe(true);
    expect(COLUMN_DEFS.some((c) => c.label === "Type")).toBe(true);
    expect(COLUMN_DEFS.some((c) => c.label === "Response")).toBe(true);
    expect(COLUMN_DEFS.some((c) => c.label === "Application URL")).toBe(false);
    expect(COLUMN_DEFS.some((c) => c.label === "Submission Type")).toBe(false);
    expect(COLUMN_DEFS.some((c) => c.label === "Response Received")).toBe(false);
  });
});
