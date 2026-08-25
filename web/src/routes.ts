import { STEPS, type StepId } from "./wizard/steps";

/** Route path constants for the app's top-level pages. */
export const ROUTES = {
  analytics: "/analytics",
  applications: "/applications",
  agents: "/agents",
  screenings: "/screenings",
  approvals: "/approvals",
  cv: "/cv",
} as const;

/** Builds the URL path for a given wizard step. */
export function stepPath(id: StepId): string {
  return `/cv/${id}`;
}

/**
 * Extracts the StepId encoded in a `/cv/:step` pathname, validating it
 * against the known STEPS rather than trusting an arbitrary segment.
 * Returns null for any path that is not a recognized wizard step path.
 */
export function stepIdFromPath(pathname: string): StepId | null {
  const prefix = "/cv/";
  if (!pathname.startsWith(prefix)) return null;
  const segment = pathname.slice(prefix.length);
  const match = STEPS.find((s) => s.id === segment);
  return match ? match.id : null;
}
