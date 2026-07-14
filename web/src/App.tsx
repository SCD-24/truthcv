import { useEffect, useState } from "react";
import Box from "@mui/material/Box";
import CircularProgress from "@mui/material/CircularProgress";
import Typography from "@mui/material/Typography";
import "./styles/shell.css";
import "./styles/settings.css";
import { STEPS, type StepId } from "./wizard/steps";
import { useWizard } from "./wizard/store";
import { StepRail } from "./wizard/StepRail";
import { UploadStep } from "./steps/UploadStep";
import { ReviewStep } from "./steps/ReviewStep";
import { PostingStep } from "./steps/PostingStep";
import { ConfirmStep } from "./steps/ConfirmStep";
import { DownloadStep } from "./steps/DownloadStep";
import { SettingsModal } from "./settings/SettingsModal";
import { ApplicationsModal } from "./applications/ApplicationsModal";

/**
 * Wizard shell. Holds the current step and how far the user has been allowed to
 * reach (the highest unlocked step), so the rail can offer back-navigation to
 * completed steps but never skip ahead past a guard. The real per-step data flow
 * and API calls live in each step component and the shared wizard store (t-3+).
 */
export function App() {
  const { bootstrap } = useWizard();
  const [current, setCurrent] = useState<StepId>("upload");
  const [reached, setReached] = useState<StepId>("upload");
  const [settingsOpen, setSettingsOpen] = useState(false);
  const [applicationsOpen, setApplicationsOpen] = useState(false);

  // Once startup resolves, open where it points. A saved profile lands the user
  // on Posting (step 3) with Upload/Review already reached, so the rail still
  // offers back-navigation to review the loaded truth.
  useEffect(() => {
    if (bootstrap === "pending") return;
    const to: StepId = bootstrap === "posting" ? "posting" : "upload";
    setCurrent(to);
    setReached(to);
  }, [bootstrap]);

  const advance = (to: StepId) => {
    setCurrent(to);
    setReached((prev) =>
      STEPS.findIndex((s) => s.id === to) > STEPS.findIndex((s) => s.id === prev)
        ? to
        : prev,
    );
  };

  const stepProps = { onAdvance: advance, onBack: setCurrent };

  if (bootstrap === "pending") {
    return (
      <Box
        className="shell shell--booting"
        role="status"
        aria-live="polite"
        sx={{ display: "flex", alignItems: "center", justifyContent: "center", gap: 2 }}
      >
        <CircularProgress size={20} sx={{ color: "var(--attest)" }} />
        <Typography variant="body1" sx={{ color: "text.secondary" }}>
          Looking for your saved profile…
        </Typography>
      </Box>
    );
  }

  return (
    <div className="shell">
      <StepRail
        current={current}
        reached={reached}
        onNavigate={setCurrent}
        onOpenSettings={() => setSettingsOpen(true)}
        onOpenApplications={() => setApplicationsOpen(true)}
      />
      <main className="stage">
        <div className="stage__inner">
          <div className="stage__step" key={current}>
            {current === "upload" && <UploadStep {...stepProps} />}
            {current === "review" && <ReviewStep {...stepProps} />}
            {current === "posting" && <PostingStep {...stepProps} />}
            {current === "confirm" && <ConfirmStep {...stepProps} />}
            {current === "download" && <DownloadStep {...stepProps} />}
          </div>
        </div>
      </main>

      {settingsOpen && <SettingsModal onClose={() => setSettingsOpen(false)} />}
      {applicationsOpen && (
        <ApplicationsModal onClose={() => setApplicationsOpen(false)} />
      )}
    </div>
  );
}
