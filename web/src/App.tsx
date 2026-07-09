import { useState } from "react";
import "./styles/shell.css";
import "./styles/settings.css";
import { STEPS, type StepId } from "./wizard/steps";
import { StepRail } from "./wizard/StepRail";
import { UploadStep } from "./steps/UploadStep";
import { ReviewStep } from "./steps/ReviewStep";
import { PostingStep } from "./steps/PostingStep";
import { ConfirmStep } from "./steps/ConfirmStep";
import { DownloadStep } from "./steps/DownloadStep";
import { SettingsModal } from "./settings/SettingsModal";

/**
 * Wizard shell. Holds the current step and how far the user has been allowed to
 * reach (the highest unlocked step), so the rail can offer back-navigation to
 * completed steps but never skip ahead past a guard. The real per-step data flow
 * and API calls live in each step component and the shared wizard store (t-3+).
 */
export function App() {
  const [current, setCurrent] = useState<StepId>("upload");
  const [reached, setReached] = useState<StepId>("upload");
  const [settingsOpen, setSettingsOpen] = useState(false);

  const advance = (to: StepId) => {
    setCurrent(to);
    setReached((prev) =>
      STEPS.findIndex((s) => s.id === to) > STEPS.findIndex((s) => s.id === prev)
        ? to
        : prev,
    );
  };

  const stepProps = { onAdvance: advance, onBack: setCurrent };

  return (
    <div className="shell">
      <StepRail current={current} reached={reached} onNavigate={setCurrent} />
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

      <footer className="footer">
        <button
          type="button"
          className="footer__settings"
          onClick={() => setSettingsOpen(true)}
        >
          <span className="footer__gear" aria-hidden="true">
            ⚙
          </span>
          Settings
        </button>
      </footer>

      {settingsOpen && <SettingsModal onClose={() => setSettingsOpen(false)} />}
    </div>
  );
}
