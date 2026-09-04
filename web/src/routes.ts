/** Route path constants for the app's top-level pages. */
export const ROUTES = {
  analytics: "/analytics",
  applications: "/applications",
  filledForm: "/applications/:id/filled-form",
  agents: "/agents",
  jobBoards: "/job-boards",
  screenings: "/screenings",
  companyResearch: "/company-research",
  approvals: "/approvals",
  onboarding: "/onboarding",
  uploadCv: "/cv",
  truthFile: "/truth",
  manual: "/manual",
  writingStyle: "/writing-style",
  documentEdit: "/documents/edit",
  browserSession: "/browser-session",
} as const;

/** Builds the URL path for an application's filled-form evidence page. */
export function filledFormPath(id: string): string {
  return `/applications/${id}/filled-form`;
}

/** Builds the URL for signing in to a site in the in-app browser session. */
export function browserSessionPath(url: string): string {
  return `/browser-session?url=${encodeURIComponent(url)}`;
}
