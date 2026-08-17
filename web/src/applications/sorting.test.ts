import { describe, expect, it } from "vitest";
import type { Application } from "../api/types";
import { COLUMN_DEFS, compareApplications, defaultCompare } from "./sorting";

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
  it("actions column is not sortable", () => {
    expect(COLUMN_DEFS[COLUMN_DEFS.length - 1].sortable).toBe(false);
  });
});
