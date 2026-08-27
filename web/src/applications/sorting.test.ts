import { describe, expect, it } from "vitest";
import type { Application } from "../api/types";
import {
  COLUMN_DEFS,
  DEFAULT_SORT_COLUMN,
  DEFAULT_SORT_DIRECTION,
  compareApplications,
  defaultCompare,
} from "./sorting";

const app = (over: Partial<Application>): Application => ({
  id: "x",
  company: "",
  website: "",
  applicationUrl: "",
  submitted: false,
  submissionType: "",
  reachedOut: false,
  toWho: "",
  responseReceived: false,
  method: "",
  posting: "",
  applicationDate: "",
  status: "",
  notes: "",
  cvDocument: null,
  coverLetterDocument: null,
  createdAt: "",
  updatedAt: "",
  ...over,
});

const col = (label: string) => COLUMN_DEFS.find((c) => c.label === label)!;

describe("sorting", () => {
  it("company sorts case-insensitively, blanks last", () => {
    const a = app({ company: "acme" }), b = app({ company: "Beta" }), blank = app({ company: "" });
    expect(compareApplications(a, b, col("Company"), "asc")).toBeLessThan(0);
    expect(compareApplications(blank, a, col("Company"), "asc")).toBeGreaterThan(0);
  });
  it("date sorts chronologically", () => {
    const early = app({ applicationDate: "2026-01-02" }), late = app({ applicationDate: "2026-03-01" });
    expect(compareApplications(early, late, col("Date"), "asc")).toBeLessThan(0);
    expect(compareApplications(early, late, col("Date"), "desc")).toBeGreaterThan(0);
  });

  it("the table defaults to newest applications first", () => {
    expect(DEFAULT_SORT_COLUMN.label).toBe("Date");
    expect(DEFAULT_SORT_DIRECTION).toBe("desc");
    const early = app({ applicationDate: "2026-01-02" }), late = app({ applicationDate: "2026-03-01" });
    const sorted = [early, late].sort((a, b) =>
      compareApplications(a, b, DEFAULT_SORT_COLUMN, DEFAULT_SORT_DIRECTION),
    );
    expect(sorted[0].applicationDate).toBe("2026-03-01");
  });

  it("undated rows stay at the bottom in BOTH directions", () => {
    // The negation that makes a column descend would otherwise lift blanks to
    // the top, filling the head of a "most recent first" table with rows that
    // have no date at all.
    const dated = app({ applicationDate: "2026-01-02" }), undated = app({ applicationDate: "" });
    expect(compareApplications(undated, dated, col("Date"), "asc")).toBeGreaterThan(0);
    expect(compareApplications(undated, dated, col("Date"), "desc")).toBeGreaterThan(0);
    expect(compareApplications(dated, undated, col("Date"), "desc")).toBeLessThan(0);
  });

  it("two undated rows are equal rather than arbitrarily ordered", () => {
    const a = app({ applicationDate: "" }), b = app({ applicationDate: "   " });
    // `=== 0` rather than toBe(0): negating for the descending direction yields
    // -0, which sorts identically but fails Object.is against +0.
    expect(compareApplications(a, b, col("Date"), "desc") === 0).toBe(true);
  });
  it("boolean columns sort yes-first ascending", () => {
    const yes = app({ submitted: true }), no = app({ submitted: false });
    expect(compareApplications(yes, no, col("Submitted"), "asc")).toBeLessThan(0);
  });
  it("status uses the status rank order", () => {
    const offer = app({ status: "Offer" }), rejected = app({ status: "Rejected" });
    expect(compareApplications(offer, rejected, col("Status"), "asc")).toBeLessThan(0);
    expect(defaultCompare(offer, rejected)).toBeLessThan(0);
  });
  it("documents sorts by presence", () => {
    const has = app({
      cvDocument: { source: "", pdfUrl: null, docxUrl: null, updatedAt: "" },
    });
    const not = app({});
    expect(compareApplications(has, not, col("Documents"), "asc")).toBeLessThan(0);
  });
  it("filled form sorts by presence", () => {
    const has = app({ fieldsSubmitted: [{ label: "Full name", value: "Jane Doe", source: "profile" }] });
    const not = app({});
    expect(compareApplications(has, not, col("Filled form"), "asc")).toBeLessThan(0);
  });
  it("actions column is not sortable", () => {
    expect(COLUMN_DEFS[COLUMN_DEFS.length - 1].sortable).toBe(false);
  });
  it("uses shortened header labels for URL, Type and Response", () => {
    expect(COLUMN_DEFS.some((c) => c.label === "URL")).toBe(true);
    expect(COLUMN_DEFS.some((c) => c.label === "Type")).toBe(true);
    expect(COLUMN_DEFS.some((c) => c.label === "Response")).toBe(true);
    expect(COLUMN_DEFS.some((c) => c.label === "Application URL")).toBe(false);
    expect(COLUMN_DEFS.some((c) => c.label === "Submission Type")).toBe(false);
    expect(COLUMN_DEFS.some((c) => c.label === "Response Received")).toBe(false);
  });
  it("all column labels are unique", () => {
    const labels = COLUMN_DEFS.map((c) => c.label);
    expect(new Set(labels).size).toBe(labels.length);
  });
});
