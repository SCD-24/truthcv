/** Route path constants for the app's top-level pages. */
export const ROUTES = {
  analytics: "/analytics",
  applications: "/applications",
  filledForm: "/applications/:id/filled-form",
  agents: "/agents",
  screenings: "/screenings",
  companyResearch: "/company-research",
  approvals: "/approvals",
  onboarding: "/onboarding",
  uploadCv: "/cv",
  manual: "/manual",
  documentEdit: "/documents/edit",
} as const;

/** Builds the URL path for an application's filled-form evidence page. */
export function filledFormPath(id: string): string {
  return `/applications/${id}/filled-form`;
}
