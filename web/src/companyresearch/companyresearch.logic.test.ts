import { describe, expect, it } from "vitest";
import {
  SOURCE_CLASSES,
  bySourceRank,
  claimKey,
  contradictionKey,
  currentByClaim,
  filterCompanies,
  formatAsOf,
  groupByClaim,
  groupFindingsByCompany,
  historyFor,
  knownCompanies,
  openContradictionKeys,
  sourceRank,
  supersededIds,
} from "./companyresearch.logic";
import type { CompanyFinding, ContradictionGroup } from "../api/types";

function makeFinding(overrides: Partial<CompanyFinding> = {}): CompanyFinding {
  return {
    id: "f1",
    company: "Acme Corp",
    companyKey: "acme corp",
    claim: "employment_entity",
    claimLabel: "",
    supersedes: "",
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
  it("groups by companyKey and sorts companies alphabetically", () => {
    const groups = groupFindingsByCompany([
      makeFinding({ id: "b", company: "Globex", companyKey: "globex" }),
      makeFinding({ id: "a", company: "Acme Corp", companyKey: "acme corp" }),
      makeFinding({ id: "c", company: "Acme Corp", companyKey: "acme corp" }),
    ]);
    expect(groups.map((g) => g.company)).toEqual(["Acme Corp", "Globex"]);
    expect(groups[0].findings.map((f) => f.id)).toEqual(["a", "c"]);
  });

  it("groups 'Acme GmbH' and 'Acme' via the same companyKey, newest spelling shown", () => {
    const groups = groupFindingsByCompany([
      makeFinding({ id: "a", company: "Acme GmbH", companyKey: "acme", observedAt: "2024-01-01" }),
      makeFinding({ id: "b", company: "Acme", companyKey: "acme", observedAt: "2024-05-01" }),
    ]);
    expect(groups).toHaveLength(1);
    expect(groups[0].company).toBe("Acme");
    expect(groups[0].findings).toHaveLength(2);
  });

  it("returns nothing for an empty list", () => {
    expect(groupFindingsByCompany([])).toEqual([]);
  });
});

describe("claimKey / groupByClaim", () => {
  it("uses the claim, except 'other' which keys on the trimmed casefolded label", () => {
    expect(claimKey(makeFinding({ claim: "employer_rating" }))).toBe("employer_rating");
    expect(claimKey(makeFinding({ claim: "other", claimLabel: "  Revenue " }))).toBe("other:revenue");
  });

  it("keeps distinct 'other' labels in distinct rows", () => {
    const groups = groupByClaim([
      makeFinding({ id: "a", claim: "other", claimLabel: "Revenue" }),
      makeFinding({ id: "b", claim: "other", claimLabel: "Headcount" }),
      makeFinding({ id: "c", claim: "other", claimLabel: "revenue " }),
    ]);
    expect(groups.map((g) => g.label)).toEqual(["Revenue", "Headcount"]);
    expect(groups[0].findings.map((f) => f.id)).toEqual(["a", "c"]);
  });

  it("labels known claims by display name and legacy claims raw", () => {
    const groups = groupByClaim([
      makeFinding({ id: "a", claim: "employment_entity" }),
      makeFinding({ id: "b", claim: "headcount" }),
    ]);
    expect(groups.map((g) => g.label)).toEqual(["Employing entity", "headcount"]);
  });
});

describe("sourceRank / bySourceRank", () => {
  it("ranks strongest first and unknown last", () => {
    expect(sourceRank("audited_accounts")).toBe(0);
    expect(sourceRank("unattributed")).toBe(SOURCE_CLASSES.length - 1);
    expect(sourceRank("hearsay")).toBe(SOURCE_CLASSES.length);
  });

  it("orders without mutating the input", () => {
    const input = [
      makeFinding({ id: "weak", sourceClass: "review_site" }),
      makeFinding({ id: "strong", sourceClass: "audited_accounts" }),
    ];
    expect(bySourceRank(input).map((f) => f.id)).toEqual(["strong", "weak"]);
    expect(input.map((f) => f.id)).toEqual(["weak", "strong"]);
  });
});

describe("formatAsOf", () => {
  it("returns the date, or literal 'unknown' when empty/blank", () => {
    expect(formatAsOf(makeFinding({ asOf: "2023-05-01" }))).toBe("2023-05-01");
    expect(formatAsOf(makeFinding({ asOf: "" }))).toBe("unknown");
    expect(formatAsOf(makeFinding({ asOf: "   " }))).toBe("unknown");
  });
});

describe("openContradictionKeys", () => {
  it("keys (companyKey, claimKey) pairs", () => {
    const groups: ContradictionGroup[] = [
      {
        claim: "employment_entity",
        findings: [makeFinding({ id: "a" }), makeFinding({ id: "b" })],
      },
    ];
    const keys = openContradictionKeys(groups);
    expect(keys.has(contradictionKey("acme corp", "employment_entity"))).toBe(true);
    expect(keys.has(contradictionKey("globex", "employment_entity"))).toBe(false);
  });
});

describe("supersededIds / currentByClaim / historyFor", () => {
  const old = makeFinding({ id: "old", value: "A", observedAt: "2024-01-01" });
  const fix = makeFinding({ id: "fix", value: "B", observedAt: "2024-03-01", supersedes: "old" });
  const rejected = makeFinding({
    id: "rej",
    value: "C",
    observedAt: "2024-04-01",
    resolution: "rejected",
  });

  it("collects superseded ids", () => {
    expect(Array.from(supersededIds([old, fix]))).toEqual(["old"]);
  });

  it("picks the newest live finding per claim, skipping superseded and rejected", () => {
    const cur = currentByClaim([old, fix, rejected]);
    expect(cur.get("employment_entity")?.id).toBe("fix");
  });

  it("history holds superseded and rejected findings, newest first", () => {
    expect(historyFor([old, fix, rejected]).map((f) => f.id)).toEqual(["rej", "old"]);
    expect(historyFor([old, fix, rejected], "employer_rating")).toEqual([]);
  });
});

describe("filterCompanies / knownCompanies", () => {
  const groups = groupFindingsByCompany([
    makeFinding({ id: "a", company: "Acme", companyKey: "acme", value: "Acme Holding AG" }),
    makeFinding({ id: "b", company: "Globex", companyKey: "globex", value: "Globex GmbH" }),
  ]);

  it("matches company or value case-insensitively", () => {
    expect(filterCompanies(groups, "GLOBEX").map((g) => g.company)).toEqual(["Globex"]);
    expect(filterCompanies(groups, "holding").map((g) => g.company)).toEqual(["Acme"]);
    expect(filterCompanies(groups, "zzz")).toEqual([]);
    expect(filterCompanies(groups, "  ")).toHaveLength(2);
  });

  it("lists distinct display names", () => {
    expect(knownCompanies(groups)).toEqual(["Acme", "Globex"]);
  });
});
