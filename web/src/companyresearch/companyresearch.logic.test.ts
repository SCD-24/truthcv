import { describe, expect, it } from "vitest";
import {
  SOURCE_CLASSES,
  bySourceRank,
  contradictionKey,
  formatAsOf,
  groupByClaim,
  groupFindingsByCompany,
  openContradictionKeys,
  sourceRank,
} from "./CompanyResearchPage";
import type { CompanyFinding, ContradictionGroup } from "../api/types";

/** A finding shaped exactly like the backend emits (api serialises camelCase),
 * with every field defaulted so a test only sets what it cares about. */
function makeFinding(overrides: Partial<CompanyFinding> = {}): CompanyFinding {
  return {
    id: "f1",
    company: "Acme Corp",
    claim: "headcount",
    value: "500",
    sourceUrl: "https://acme.example/about",
    sourceClass: "company_statement",
    asOf: "2024-01-01",
    observedAt: "2024-06-01T12:00:00+00:00",
    recordedBy: "operator",
    note: "",
    contradicts: [],
    resolution: "",
    resolvedAt: "",
    resolutionNote: "",
    ...overrides,
  };
}

describe("groupFindingsByCompany", () => {
  it("groups by company, preserving first-seen order", () => {
    const groups = groupFindingsByCompany([
      makeFinding({ id: "a", company: "Acme Corp" }),
      makeFinding({ id: "b", company: "Globex" }),
      makeFinding({ id: "c", company: "Acme Corp" }),
    ]);
    expect(groups.map((g) => g.company)).toEqual(["Acme Corp", "Globex"]);
    expect(groups[0].findings.map((f) => f.id)).toEqual(["a", "c"]);
    expect(groups[1].findings.map((f) => f.id)).toEqual(["b"]);
  });

  it("returns nothing for an empty list", () => {
    expect(groupFindingsByCompany([])).toEqual([]);
  });
});

describe("groupByClaim", () => {
  it("groups by claim, preserving first-seen order", () => {
    const groups = groupByClaim([
      makeFinding({ id: "a", claim: "headcount" }),
      makeFinding({ id: "b", claim: "revenue" }),
      makeFinding({ id: "c", claim: "headcount" }),
    ]);
    expect(groups.map((g) => g.claim)).toEqual(["headcount", "revenue"]);
    expect(groups[0].findings.map((f) => f.id)).toEqual(["a", "c"]);
  });
});

describe("sourceRank", () => {
  it("ranks audited accounts strongest and unattributed weakest", () => {
    expect(sourceRank("audited_accounts")).toBe(0);
    expect(sourceRank("unattributed")).toBe(SOURCE_CLASSES.length - 1);
    expect(sourceRank("audited_accounts")).toBeLessThan(sourceRank("press"));
    expect(sourceRank("press")).toBeLessThan(sourceRank("review_site"));
  });

  it("ranks an unknown class below every known one", () => {
    expect(sourceRank("hearsay")).toBe(SOURCE_CLASSES.length);
    expect(sourceRank("hearsay")).toBeGreaterThan(sourceRank("unattributed"));
  });
});

describe("bySourceRank", () => {
  it("orders strongest source first without mutating the input", () => {
    const input = [
      makeFinding({ id: "weak", sourceClass: "review_site" }),
      makeFinding({ id: "strong", sourceClass: "audited_accounts" }),
      makeFinding({ id: "mid", sourceClass: "press" }),
    ];
    expect(bySourceRank(input).map((f) => f.id)).toEqual(["strong", "mid", "weak"]);
    // Input order is untouched.
    expect(input.map((f) => f.id)).toEqual(["weak", "strong", "mid"]);
  });
});

describe("formatAsOf", () => {
  it("returns the as-of date when present", () => {
    expect(formatAsOf(makeFinding({ asOf: "2023-05-01" }))).toBe("2023-05-01");
  });

  it("returns the literal 'unknown' for an empty as-of, never observedAt", () => {
    const finding = makeFinding({ asOf: "", observedAt: "2024-06-01T12:00:00+00:00" });
    expect(formatAsOf(finding)).toBe("unknown");
  });

  it("treats a whitespace-only as-of as unknown", () => {
    expect(formatAsOf(makeFinding({ asOf: "   " }))).toBe("unknown");
  });
});

describe("openContradictionKeys", () => {
  it("keys every (company, claim) pair the contradiction groups report", () => {
    const groups: ContradictionGroup[] = [
      {
        claim: "headcount",
        findings: [
          makeFinding({ id: "a", company: "Acme Corp", claim: "headcount" }),
          makeFinding({ id: "b", company: "Acme Corp", claim: "headcount" }),
        ],
      },
    ];
    const keys = openContradictionKeys(groups);
    expect(keys.has(contradictionKey("Acme Corp", "headcount"))).toBe(true);
    expect(keys.has(contradictionKey("Globex", "headcount"))).toBe(false);
  });
});
