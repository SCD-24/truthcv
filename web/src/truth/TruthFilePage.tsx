import { useState } from "react";
import Alert from "@mui/material/Alert";
import { ReviewStep } from "../steps/ReviewStep";

/**
 * The Truth File dedicated page: loads the persisted truth file and renders
 * it in the ReviewStep editor. On successful save, shows a success alert and
 * stays on the page (does not navigate). The user can review, edit, add
 * user-sourced entries, and remove any entry (CV-sourced or user-added).
 */
export function TruthFilePage({ onBack }: { onBack: () => void }) {
  const [savedAlert, setSavedAlert] = useState(false);

  const handleNext = async () => {
    // ReviewStep.save already called saveTruth and setTruth; we just need to
    // show a success alert and stay on the page.
    setSavedAlert(true);
  };

  return (
    <div>
      {savedAlert && (
        <Alert
          severity="success"
          onClose={() => setSavedAlert(false)}
          sx={{ mb: 2 }}
        >
          Truth file saved.
        </Alert>
      )}
      <ReviewStep
        eyebrow="Truth file"
        title="Your truth file"
        lede="Every fact a CV may contain lives here. Correct, remove, or add entries — anything you add is stamped as confirmed by you and applies to every CV you generate from now on."
        nextLabel="Save"
        onNext={handleNext}
        onBack={onBack}
      />
    </div>
  );
}
