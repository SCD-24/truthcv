import { useState } from "react";
import { UploadStep } from "../steps/UploadStep";
import { ReviewStep } from "../steps/ReviewStep";
import { updateOnboarding } from "../api/client";

interface Props {
  /** Called once the CV has been uploaded and reviewed. */
  onDone: () => void;
  /** Which phase to open on. Defaults to "upload". */
  initialPhase?: "upload" | "review";
}

/**
 * The reusable Upload → Review body: a local two-phase flow (Upload, then
 * Review) — not routes, not the global wizard rail. Opens on `initialPhase`
 * (default "upload"); callers that already know a profile PDF exists (e.g.
 * onboarding) can start it on Review instead of asking the user to re-upload.
 * Marks the onboarding CV review as done on the server once Review is saved,
 * then hands off to onDone. Shared by the standalone Upload CV page and the
 * first-run onboarding flow.
 */
export function UploadReviewFlow({ onDone, initialPhase = "upload" }: Props) {
  const [phase, setPhase] = useState<"upload" | "review">(initialPhase);

  const finishReview = async () => {
    try {
      await updateOnboarding({ cvReviewedAt: new Date().toISOString() });
    } catch (err) {
      console.error("Failed to record CV review", err);
    }
    onDone();
  };

  if (phase === "upload") {
    return <UploadStep onNext={() => setPhase("review")} />;
  }
  return <ReviewStep onNext={finishReview} onBack={() => setPhase("upload")} />;
}

/**
 * The Upload CV destination: a thin wrapper around {@link UploadReviewFlow}.
 * Kept as its own export so existing routes/callers keep their `onDone` prop.
 */
export function UploadCvPage({ onDone }: Props) {
  return <UploadReviewFlow onDone={onDone} />;
}
