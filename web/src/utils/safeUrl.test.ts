import { describe, expect, it } from "vitest";
import { safeHref } from "./safeUrl";

describe("safeHref", () => {
  it("prepends https:// to a bare host", () => {
    expect(safeHref("example.com")).toBe("https://example.com");
  });
  it("passes http:// and https:// URLs through unchanged", () => {
    expect(safeHref("https://x")).toBe("https://x");
    expect(safeHref("http://x")).toBe("http://x");
  });
  it("passes mailto: and tel: through unchanged", () => {
    expect(safeHref("mailto:a@b.com")).toBe("mailto:a@b.com");
    expect(safeHref("tel:+123")).toBe("tel:+123");
  });
  it("rejects a javascript: scheme", () => {
    expect(safeHref("javascript:alert(1)")).toBeNull();
  });
  it("rejects a data: scheme", () => {
    expect(safeHref("data:text/html,<script>alert(1)</script>")).toBeNull();
  });
  it("rejects a javascript: scheme with surrounding whitespace", () => {
    expect(safeHref("  javascript:alert(1)  ")).toBeNull();
  });
  it("rejects an empty string", () => {
    expect(safeHref("")).toBeNull();
  });
});
