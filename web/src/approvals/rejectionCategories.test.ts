import { describe, expect, it } from "vitest";
import {
  categoryLabel,
  categoryOf,
  countByCategory,
  filterByCategory,
} from "./rejectionCategories";

const r = (failingCriterion: string) => ({ failingCriterion });

describe("rejectionCategories", () => {
  it("categoryOf maps empty, known and unknown", () => {
    expect(categoryOf(r(""))).toBe("none");
    expect(categoryOf(r("salary_floor"))).toBe("salary_floor");
    expect(categoryOf(r("some free text"))).toBe("other");
    expect(categoryOf(r("toString"))).toBe("other");
  });

  it("categoryLabel returns labels", () => {
    expect(categoryLabel("eor_allowed")).toBe("EOR / PEO");
    expect(categoryLabel("none")).toBe("No reason given");
  });

  it("countByCategory is in label order and only present", () => {
    const rows = [r(""), r("role_fit"), r("remote_model"), r("role_fit"), r("zzz")];
    expect(countByCategory(rows)).toEqual([
      { key: "remote_model", count: 1 },
      { key: "role_fit", count: 2 },
      { key: "other", count: 1 },
      { key: "none", count: 1 },
    ]);
  });

  it("filterByCategory filters or passes all", () => {
    const rows = [r(""), r("role_fit"), r("zzz")];
    expect(filterByCategory(rows, "all")).toHaveLength(3);
    expect(filterByCategory(rows, "other")).toEqual([r("zzz")]);
    expect(filterByCategory(rows, "none")).toEqual([r("")]);
  });
});
