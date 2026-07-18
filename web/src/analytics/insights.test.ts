import { describe, expect, it } from "vitest";
import type { Application, ApplicationDocument } from "../api/types";
import { computeInsights, NEEDS_ATTENTION_DAYS } from "./insights";

/** A fixed "now" so age-based logic (needs-attention) is deterministic. */
const NOW = Date.parse("2024-06-15T00:00:00Z");

/** Build an Application with sensible defaults, overridable per test. */
function makeApp(overrides: Partial<Application> = {}): Application {
  return {
    id: Math.random().toString(36).slice(2),
    company: "Acme",
    website: "acme.com",
    applicationUrl: "https://acme.com/apply",
    submitted: false,
    submissionType: "General",
    reachedOut: false,
    toWho: "",
    responseReceived: false,
    method: "",
    posting: "",
    applicationDate: "2024-06-01",
    status: "",
    notes: "",
    cvDocument: null,
    coverLetterDocument: null,
    createdAt: "2024-06-01T00:00:00Z",
    updatedAt: "2024-06-01T00:00:00Z",
    ...overrides,
  };
}

/** A minimal attached document. */
function doc(): ApplicationDocument {
  return { source: "<p>cv</p>", pdfUrl: null, docxUrl: null, updatedAt: "" };
}

/** A date `days` before NOW, as YYYY-MM-DD. */
function daysAgo(days: number): string {
  return new Date(NOW - days * 86_400_000).toISOString().slice(0, 10);
}

describe("computeInsights — empty input", () => {
  it("returns zeroed totals and rates without dividing by zero", () => {
    const insights = computeInsights([], NOW);
    expect(insights.totals).toEqual({
      total: 0,
      submitted: 0,
      drafts: 0,
      docsAttached: 0,
    });
    expect(insights.rates).toEqual({
      responseRate: 0,
      outreachRate: 0,
      docAttachRate: 0,
    });
    expect(insights.timeSeries).toEqual([]);
    expect(insights.needsAttention).toEqual([]);
    expect(insights.dataGaps).toEqual([]);
  });

  it("guards per-segment rates against zero denominators", () => {
    const { responseByOutreach } = computeInsights([], NOW);
    expect(responseByOutreach.withOutreach.rate).toBe(0);
    expect(responseByOutreach.withoutOutreach.rate).toBe(0);
  });
});

describe("computeInsights — totals and rates", () => {
  it("counts submitted, drafts, and attached documents", () => {
    const apps = [
      makeApp({ submitted: true, cvDocument: doc() }),
      makeApp({ submitted: true }),
      makeApp({ submitted: false, coverLetterDocument: doc() }),
    ];
    const { totals } = computeInsights(apps, NOW);
    expect(totals).toEqual({ total: 3, submitted: 2, drafts: 1, docsAttached: 2 });
  });

  it("computes response, outreach, and doc-attach rates", () => {
    const apps = [
      makeApp({ submitted: true, responseReceived: true, reachedOut: true, cvDocument: doc() }),
      makeApp({ submitted: true, responseReceived: false, reachedOut: false }),
      makeApp({ submitted: false, reachedOut: true, cvDocument: doc() }),
      makeApp({ submitted: false }),
    ];
    const { rates } = computeInsights(apps, NOW);
    expect(rates.responseRate).toBeCloseTo(1 / 2); // 1 responded of 2 submitted
    expect(rates.outreachRate).toBeCloseTo(2 / 4); // 2 reached out of 4 total
    expect(rates.docAttachRate).toBeCloseTo(2 / 4); // 2 with a doc of 4 total
  });
});

describe("computeInsights — response by outreach", () => {
  it("splits response rate by whether the user reached out", () => {
    const apps = [
      makeApp({ submitted: true, reachedOut: true, responseReceived: true }),
      makeApp({ submitted: true, reachedOut: true, responseReceived: false }),
      makeApp({ submitted: true, reachedOut: false, responseReceived: false }),
    ];
    const { responseByOutreach } = computeInsights(apps, NOW);
    expect(responseByOutreach.withOutreach).toEqual({
      submitted: 2,
      responded: 1,
      rate: 0.5,
    });
    expect(responseByOutreach.withoutOutreach).toEqual({
      submitted: 1,
      responded: 0,
      rate: 0,
    });
  });
});

describe("computeInsights — breakdowns", () => {
  it("groups by status/type/method with per-segment response counts", () => {
    const apps = [
      makeApp({ status: "Applied", method: "Email", submitted: true, responseReceived: true }),
      makeApp({ status: "Applied", method: "Email", submitted: true }),
      makeApp({ status: "Rejected", method: "LinkedIn", submitted: true }),
    ];
    const insights = computeInsights(apps, NOW);
    const applied = insights.byStatus.find((b) => b.label === "Applied");
    expect(applied).toEqual({ label: "Applied", count: 2, submitted: 2, responded: 1 });
    const email = insights.byMethod.find((b) => b.label === "Email");
    expect(email).toEqual({ label: "Email", count: 2, submitted: 2, responded: 1 });
    // Sorted by count descending.
    expect(insights.byStatus[0].count).toBeGreaterThanOrEqual(
      insights.byStatus[1].count,
    );
  });

  it("labels blank segments as an em dash", () => {
    const { bySubmissionType } = computeInsights([makeApp({ submissionType: "" })], NOW);
    expect(bySubmissionType[0].label).toBe("—");
  });
});

describe("computeInsights — month bucketing", () => {
  it("buckets by YYYY-MM and skips blank/invalid dates", () => {
    const apps = [
      makeApp({ applicationDate: "2024-05-10", submitted: true, responseReceived: true }),
      makeApp({ applicationDate: "2024-05-22" }),
      makeApp({ applicationDate: "2024-06-03" }),
      makeApp({ applicationDate: "" }),
      makeApp({ applicationDate: "not-a-date" }),
    ];
    const { timeSeries } = computeInsights(apps, NOW);
    expect(timeSeries.map((b) => b.month)).toEqual(["2024-05", "2024-06"]);
    expect(timeSeries[0].applied).toBe(2);
    expect(timeSeries[0].responded).toBe(1);
  });

  it("accumulates cumulative applied and responded chronologically", () => {
    const apps = [
      makeApp({ applicationDate: "2024-04-01", responseReceived: true }),
      makeApp({ applicationDate: "2024-05-01" }),
      makeApp({ applicationDate: "2024-06-01", responseReceived: true }),
    ];
    const { timeSeries } = computeInsights(apps, NOW);
    expect(timeSeries.map((b) => b.cumulativeApplied)).toEqual([1, 2, 3]);
    expect(timeSeries.map((b) => b.cumulativeResponded)).toEqual([1, 1, 2]);
  });
});

describe("computeInsights — needs attention", () => {
  it("excludes an application 13 days old (below the threshold)", () => {
    const apps = [
      makeApp({ submitted: true, responseReceived: false, applicationDate: daysAgo(13) }),
    ];
    expect(computeInsights(apps, NOW).needsAttention).toHaveLength(0);
  });

  it(`includes an application exactly ${NEEDS_ATTENTION_DAYS} days old`, () => {
    const apps = [
      makeApp({
        submitted: true,
        responseReceived: false,
        applicationDate: daysAgo(NEEDS_ATTENTION_DAYS),
      }),
    ];
    expect(computeInsights(apps, NOW).needsAttention).toHaveLength(1);
  });

  it("excludes drafts, answered, and undated applications", () => {
    const apps = [
      makeApp({ submitted: false, applicationDate: daysAgo(30) }),
      makeApp({ submitted: true, responseReceived: true, applicationDate: daysAgo(30) }),
      makeApp({ submitted: true, responseReceived: false, applicationDate: "" }),
    ];
    expect(computeInsights(apps, NOW).needsAttention).toHaveLength(0);
  });
});

describe("computeInsights — data gaps", () => {
  it("flags missing website, application URL, and document", () => {
    const apps = [
      makeApp({ website: "", applicationUrl: "N/A", cvDocument: null }),
    ];
    const { dataGaps } = computeInsights(apps, NOW);
    expect(dataGaps).toHaveLength(1);
    expect(dataGaps[0].missing).toEqual(["website", "application URL", "document"]);
  });

  it("reports no gaps for a complete application", () => {
    const apps = [makeApp({ cvDocument: doc() })];
    expect(computeInsights(apps, NOW).dataGaps).toHaveLength(0);
  });
});
