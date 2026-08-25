import type { ReactNode } from "react";
import { Navigate, useLocation } from "react-router-dom";
import { useWizard } from "./store";
import type { StepId } from "./steps";
import type { TruthDoc } from "../api/types";

interface GuardState {
  hasProfile: boolean;
  truth: TruthDoc;
  inferences: unknown[];
  render: unknown;
  coverLetter: unknown;
  hasEditRequest: boolean;
}

/** Whether any real content has been loaded into the truth file this session. */
function hasTruthData(truth: TruthDoc): boolean {
  return (
    truth.experiences.length > 0 ||
    truth.education.length > 0 ||
    truth.skills.length > 0 ||
    truth.profile.name.trim() !== ""
  );
}

/**
 * Pure predicate: whether `step` may be entered given the wizard's current
 * state. Kept separate from StepGuard so it is trivially unit-testable and
 * keeps the component itself under the nesting/length limits.
 *
 * "review" needs truth data to display, satisfied either by a saved profile
 * (hasProfile) or by an upload done earlier this session. "posting" has no
 * such prerequisite — it is a plain text box — so it is always reachable,
 * which is also what lets a guarded fallback (e.g. from "confirm") land
 * without a further redirect.
 */
export function stepAllowed(step: StepId, state: GuardState): boolean {
  if (step === "review") return state.hasProfile || hasTruthData(state.truth);
  if (step === "confirm") return state.inferences.length > 0;
  if (step === "download") {
    return Boolean(state.render || state.coverLetter || state.hasEditRequest);
  }
  return true;
}

/** Redirect target for a step whose prerequisites are not met. */
function fallbackFor(step: StepId): string {
  if (step === "review") return "/cv/upload";
  return "/cv/posting";
}

/**
 * Guards a deep-linked wizard step: redirects to the furthest step its
 * prerequisites support when the in-memory wizard data required to render it
 * (never persisted across a refresh) is missing.
 */
export function StepGuard({ step, children }: { step: StepId; children: ReactNode }) {
  const wizard = useWizard();
  const location = useLocation();

  if (wizard.bootstrap === "pending") return null;

  const hasEditRequest = Boolean(
    (location.state as { editRequest?: unknown } | null)?.editRequest,
  );
  const allowed = stepAllowed(step, {
    hasProfile: wizard.hasProfile,
    truth: wizard.truth,
    inferences: wizard.inferences,
    render: wizard.render,
    coverLetter: wizard.coverLetter,
    hasEditRequest,
  });

  if (!allowed) return <Navigate to={fallbackFor(step)} replace />;
  return <>{children}</>;
}
