import { describe, it, expect } from "vitest";
import { errorDetailToMessage } from "./errorDetail";

describe("errorDetailToMessage — string detail", () => {
  it("passes a string detail through unchanged", () => {
    expect(errorDetailToMessage({ detail: "Company already blocked" })).toBe(
      "Company already blocked",
    );
  });
});

describe("errorDetailToMessage — array detail", () => {
  it("formats a single validation error as 'field: msg'", () => {
    const body = {
      detail: [
        { loc: ["body", "profiles"], msg: "profile name must not be empty", type: "value_error" },
      ],
    };
    expect(errorDetailToMessage(body)).toBe("profiles: profile name must not be empty");
  });

  it("formats multiple validation errors, joined with '; '", () => {
    const body = {
      detail: [
        { loc: ["body", "profiles"], msg: "profile name must not be empty", type: "value_error" },
        { loc: ["body", "salaryFloor"], msg: "must be > 0", type: "value_error" },
      ],
    };
    expect(errorDetailToMessage(body)).toBe(
      "profiles: profile name must not be empty; salaryFloor: must be > 0",
    );
  });

  it("returns an empty string for an empty array detail", () => {
    expect(errorDetailToMessage({ detail: [] })).toBe("");
  });
});

describe("errorDetailToMessage — unparseable bodies", () => {
  it("returns an empty string for null", () => {
    expect(errorDetailToMessage(null)).toBe("");
  });

  it("returns an empty string for undefined", () => {
    expect(errorDetailToMessage(undefined)).toBe("");
  });

  it("returns an empty string for a garbage body", () => {
    expect(errorDetailToMessage("not an object")).toBe("");
    expect(errorDetailToMessage(42)).toBe("");
    expect(errorDetailToMessage({})).toBe("");
  });
});
