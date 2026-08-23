import { useCallback, useEffect, useState } from "react";
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
import { ApplicationsPage } from "./applications/ApplicationsPage";
import { AnalyticsPage } from "./analytics/AnalyticsPage";
import { AgentsPage } from "./agents/AgentsPage";
import { ScreeningsPage } from "./screenings/ScreeningsPage";
import { ApprovalsPage } from "./approvals/ApprovalsPage";
import { listPendingApprovals } from "./api/client";

/**
 * Top-level view: the wizard, the applications ledger, its analytics, the
 * agents page, or the screenings page.
 */
type View =
  | "wizard"
  | "applications"
  | "analytics"
  | "agents"
  | "screenings"
  | "approvals";

/**
 * A request to open the Download step (step 5) with an already-saved document
 * loaded for re-editing — fired when the user clicks a document in the ledger.
 * `source` is the saved CV HTML / cover-letter text; `appId` is the application
 * the re-save must update.
 */
export type EditRequest = {
  appId: string;
  kind: "cv" | "cover-letter";
  source: string;
};

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
  const [view, setView] = useState<View>("wizard");
  // Pending-approval count for the rail badge; refreshed on mount and whenever
  // the Approvals page is left, since decisions there change it.
  const [pendingApprovals, setPendingApprovals] = useState(0);

  // A failure here leaves the badge at its last value rather than surfacing an
  // error: the count is an affordance, and the page itself reports problems.
  const refreshPendingApprovals = useCallback(() => {
    listPendingApprovals()
      .then((rows) => setPendingApprovals(rows.length))
      .catch(() => {});
  }, []);

  useEffect(() => {
    refreshPendingApprovals();
  }, [refreshPendingApprovals]);
  // A saved document the user chose to re-edit from the ledger, if any. When
  // set, the Download step opens seeded with it instead of a fresh render.
  const [editRequest, setEditRequest] = useState<EditRequest | null>(null);

  // Open step 5 (Download) with a saved document loaded for re-editing. Jump
  // straight there and mark it reached so the rail offers back-navigation.
  const openDocumentEditor = (req: EditRequest) => {
    setEditRequest(req);
    setView("wizard");
    setCurrent("download");
    setReached("download");
  };

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
        onNavigate={(to) => {
          setView("wizard");
          setCurrent(to);
          // Leaving via the rail abandons any ledger-driven edit request so the
          // Download step returns to its normal generate-and-download flow.
          if (to !== "download") setEditRequest(null);
        }}
        onOpenSettings={() => setSettingsOpen(true)}
        onOpenApplications={() => setView("applications")}
        onOpenAnalytics={() => setView("analytics")}
        onOpenAgents={() => setView("agents")}
        onOpenScreenings={() => setView("screenings")}
        onOpenApprovals={() => setView("approvals")}
        applicationsActive={view === "applications"}
        analyticsActive={view === "analytics"}
        agentsActive={view === "agents"}
        screeningsActive={view === "screenings"}
        approvalsActive={view === "approvals"}
        pendingApprovals={pendingApprovals}
      />
      <main className="stage">
        <div
          className={
            view !== "wizard"
              ? "stage__inner stage__inner--wide"
              : "stage__inner"
          }
        >
          {view === "applications" ? (
            <ApplicationsPage
              onBack={() => setView("wizard")}
              onEditDocument={openDocumentEditor}
            />
          ) : view === "analytics" ? (
            <AnalyticsPage onBack={() => setView("wizard")} />
          ) : view === "agents" ? (
            <AgentsPage onBack={() => setView("wizard")} />
          ) : view === "screenings" ? (
            <ScreeningsPage onBack={() => setView("wizard")} />
          ) : view === "approvals" ? (
            <ApprovalsPage
              onBack={() => {
                setView("wizard");
                refreshPendingApprovals();
              }}
            />
          ) : (
            <div className="stage__step" key={current}>
              {current === "upload" && <UploadStep {...stepProps} />}
              {current === "review" && <ReviewStep {...stepProps} />}
              {current === "posting" && <PostingStep {...stepProps} />}
              {current === "confirm" && <ConfirmStep {...stepProps} />}
              {current === "download" && (
                <DownloadStep
                  {...stepProps}
                  editRequest={editRequest}
                  onEditDone={() => setEditRequest(null)}
                />
              )}
            </div>
          )}
        </div>
      </main>

      {settingsOpen && <SettingsModal onClose={() => setSettingsOpen(false)} />}
    </div>
  );
}
