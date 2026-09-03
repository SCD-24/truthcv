import { describe, expect, it } from "vitest";
import { COLUMN_DEFS, DEFAULT_SORT_COLUMN, DEFAULT_SORT_DIRECTION } from "./sorting";

describe("sorting", () => {
  it("the table defaults to newest applications first", () => {
    expect(DEFAULT_SORT_COLUMN.label).toBe("Date");
    expect(DEFAULT_SORT_COLUMN.sortKey).toBe("date");
    expect(DEFAULT_SORT_DIRECTION).toBe("desc");
  });

  it("every sortable column carries a server sort key", () => {
    for (const col of COLUMN_DEFS) {
      if (col.sortable) {
        expect(col.sortKey, col.label).toBeDefined();
        expect(typeof col.sortKey).toBe("string");
      }
    }
  });

  it("the actions column is not sortable and has no sort key", () => {
    const actions = COLUMN_DEFS[COLUMN_DEFS.length - 1];
    expect(actions.sortable).toBe(false);
    expect(actions.sortKey).toBeUndefined();
  });

  it("maps each remaining column to its server sort key", () => {
    const expected: Record<string, string> = {
      Company: "company",
      Date: "date",
      Submitted: "submitted",
      Type: "type",
      Status: "status",
      "Reached Out": "reachedOut",
      "To Who": "toWho",
      Response: "response",
      Method: "method",
      Notes: "notes",
    };
    for (const [label, key] of Object.entries(expected)) {
      const col = COLUMN_DEFS.find((c) => c.label === label);
      expect(col, label).toBeDefined();
      expect(col?.sortable).toBe(true);
      expect(col?.sortKey).toBe(key);
    }
  });

  it("no longer has the columns folded into the links line", () => {
    // Website, URL, Posting, Documents and Filled form live under the company
    // name now (ApplicationLinks), not as sortable table columns.
    for (const label of ["Website", "URL", "Posting", "Documents", "Filled form"]) {
      expect(COLUMN_DEFS.some((c) => c.label === label), label).toBe(false);
    }
  });

  it("uses shortened header labels for Type and Response", () => {
    expect(COLUMN_DEFS.some((c) => c.label === "Type")).toBe(true);
    expect(COLUMN_DEFS.some((c) => c.label === "Response")).toBe(true);
    expect(COLUMN_DEFS.some((c) => c.label === "Submission Type")).toBe(false);
    expect(COLUMN_DEFS.some((c) => c.label === "Response Received")).toBe(false);
  });

  it("all column labels are unique", () => {
    const labels = COLUMN_DEFS.map((c) => c.label);
    expect(new Set(labels).size).toBe(labels.length);
  });
});
