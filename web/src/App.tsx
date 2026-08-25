import { useCallback, useEffect, useState } from "react";
import { Navigate, Route, Routes, useLocation, useNavigate } from "react-router-dom";
import Box from "@mui/material/Box";
import CircularProgress from "@mui/material/CircularProgress";
import Typography from "@mui/material/Typography";
import "./styles/shell.css";
import "./styles/settings.css";
import { type StepId } from "./wizard/steps";
import { useWizard } from "./wizard/store";
import { StepRail } from "./wizard/StepRail";
import { StepGuard } from "./wizard/StepGuard";
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
import { ROUTES, stepIdFromPath, stepPath } from "./routes";

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

/** Splash shown while the startup profile check is in flight. */
function BootSplash() {
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

/** Hook: pending-approvals badge count, refreshed on every navigation. */
function usePendingApprovalsBadge(pathname: string): number {
  const [pendingApprovals, setPendingApprovals] = useState(0);

  const refresh = useCallback(() => {
    listPendingApprovals()
      .then((rows) => setPendingApprovals(rows.length))
      .catch(() => {});
  }, []);

  useEffect(() => {
    refresh();
  }, [refresh, pathname]);

  return pendingApprovals;
}

interface ShellNavProps {
  activeStep: StepId;
  pathname: string;
  onOpenSettings: () => void;
  pendingApprovals: number;
}

/** The step rail plus its top-level page buttons, routed via navigate(). */
function ShellNav({ activeStep, pathname, onOpenSettings, pendingApprovals }: ShellNavProps) {
  const navigate = useNavigate();
  return (
    <StepRail
      current={activeStep}
      reached={activeStep}
      onNavigate={(to) => navigate(stepPath(to))}
      onOpenSettings={onOpenSettings}
      onOpenApplications={() => navigate(ROUTES.applications)}
      onOpenAnalytics={() => navigate(ROUTES.analytics)}
      onOpenAgents={() => navigate(ROUTES.agents)}
      onOpenScreenings={() => navigate(ROUTES.screenings)}
      onOpenApprovals={() => navigate(ROUTES.approvals)}
      applicationsActive={pathname === ROUTES.applications}
      analyticsActive={pathname === ROUTES.analytics}
      agentsActive={pathname === ROUTES.agents}
      screeningsActive={pathname === ROUTES.screenings}
      approvalsActive={pathname === ROUTES.approvals}
      pendingApprovals={pendingApprovals}
    />
  );
}

/** The five wizard step routes, each guarded against missing prerequisites. */
function CvStepRoutes() {
  const navigate = useNavigate();
  const location = useLocation();
  const stepProps = {
    onAdvance: (to: StepId) => navigate(stepPath(to)),
    onBack: (to: StepId) => navigate(stepPath(to)),
  };
  const editRequest =
    (location.state as { editRequest?: EditRequest } | null)?.editRequest ?? null;
  const onEditDone = () => navigate(location.pathname, { replace: true, state: null });

  return (
    <Routes>
      <Route path="upload" element={<StepGuard step="upload"><UploadStep {...stepProps} /></StepGuard>} />
      <Route path="review" element={<StepGuard step="review"><ReviewStep {...stepProps} /></StepGuard>} />
      <Route path="posting" element={<StepGuard step="posting"><PostingStep {...stepProps} /></StepGuard>} />
      <Route path="confirm" element={<StepGuard step="confirm"><ConfirmStep {...stepProps} /></StepGuard>} />
      <Route
        path="download"
        element={
          <StepGuard step="download">
            <DownloadStep {...stepProps} editRequest={editRequest} onEditDone={onEditDone} />
          </StepGuard>
        }
      />
    </Routes>
  );
}

/** The app's top-level page routes (everything outside `/cv/*`). */
function TopLevelRoutes({ bootstrap }: { bootstrap: "upload" | "posting" }) {
  const navigate = useNavigate();
  const onBack = () => navigate(ROUTES.cv);
  const onEditDocument = (req: EditRequest) =>
    navigate("/cv/download", { state: { editRequest: req } });

  return (
    <Routes>
      <Route path="/" element={<Navigate to={ROUTES.analytics} replace />} />
      <Route path={ROUTES.analytics} element={<AnalyticsPage onBack={onBack} />} />
      <Route
        path={ROUTES.applications}
        element={<ApplicationsPage onBack={onBack} onEditDocument={onEditDocument} />}
      />
      <Route path={ROUTES.agents} element={<AgentsPage onBack={onBack} />} />
      <Route path={ROUTES.screenings} element={<ScreeningsPage onBack={onBack} />} />
      <Route path={ROUTES.approvals} element={<ApprovalsPage onBack={onBack} />} />
      <Route
        path="/cv"
        element={<Navigate replace to={bootstrap === "posting" ? "/cv/posting" : "/cv/upload"} />}
      />
      <Route path="/cv/*" element={<CvStepRoutes />} />
      <Route path="*" element={<Navigate to={ROUTES.analytics} replace />} />
    </Routes>
  );
}

/**
 * App shell. Every page — including the manual CV wizard at /cv/* — is a real
 * URL, so a browser refresh lands back on the same page (or, for a wizard step
 * whose in-memory prerequisites are gone, the furthest step that still
 * supports it — see StepGuard).
 */
export function App() {
  const { bootstrap } = useWizard();
  const [settingsOpen, setSettingsOpen] = useState(false);
  const location = useLocation();
  const pendingApprovals = usePendingApprovalsBadge(location.pathname);

  if (bootstrap === "pending") return <BootSplash />;

  const activeStep = stepIdFromPath(location.pathname) ?? "upload";
  const isWizard = location.pathname.startsWith(ROUTES.cv);

  return (
    <div className="shell">
      <ShellNav
        activeStep={activeStep}
        pathname={location.pathname}
        onOpenSettings={() => setSettingsOpen(true)}
        pendingApprovals={pendingApprovals}
      />
      <main className="stage">
        <div className={isWizard ? "stage__inner" : "stage__inner stage__inner--wide"}>
          <div className={isWizard ? "stage__step" : undefined} key={isWizard ? activeStep : "page"}>
            <TopLevelRoutes bootstrap={bootstrap} />
          </div>
        </div>
      </main>

      {settingsOpen && <SettingsModal onClose={() => setSettingsOpen(false)} />}
    </div>
  );
}
