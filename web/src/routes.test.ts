import { describe, expect, it } from "vitest";
import { ROUTES, filledFormPath } from "./routes";

describe("ROUTES", () => {
  it("defines the app's top-level destinations", () => {
    expect(ROUTES.analytics).toBe("/analytics");
    expect(ROUTES.applications).toBe("/applications");
    expect(ROUTES.agents).toBe("/agents");
    expect(ROUTES.screenings).toBe("/screenings");
    expect(ROUTES.companyResearch).toBe("/company-research");
    expect(ROUTES.approvals).toBe("/approvals");
    expect(ROUTES.onboarding).toBe("/onboarding");
    expect(ROUTES.uploadCv).toBe("/cv");
    expect(ROUTES.manual).toBe("/manual");
    expect(ROUTES.documentEdit).toBe("/documents/edit");
  });

  it("builds the filled-form path for an application id", () => {
    expect(filledFormPath("abc")).toBe("/applications/abc/filled-form");
  });
});
