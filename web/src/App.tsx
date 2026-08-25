import { useCallback, useEffect, useState } from "react";
import { Navigate, Route, Routes, useLocation, useNavigate } from "react-router-dom";
import Box from "@mui/material/Box";
import Button from "@mui/material/Button";
import CircularProgress from "@mui/material/CircularProgress";
import Typography from "@mui/material/Typography";
import "./styles/shell.css";
import "./styles/settings.css";
import { useWizard } from "./wizard/store";
import { SideNav } from "./nav/SideNav";
import { SettingsModal } from "./settings/SettingsModal";
import { ApplicationsPage } from "./applications/ApplicationsPage";
import { FilledFormPage } from "./applications/FilledFormPage";
import { AnalyticsPage } from "./analytics/AnalyticsPage";
import { AgentsPage } from "./agents/AgentsPage";
import { ScreeningsPage } from "./screenings/ScreeningsPage";
import { ApprovalsPage } from "./approvals/ApprovalsPage";
import { UploadCvPage } from "./cv/UploadCvPage";
import { ManualPage } from "./manual/ManualPage";
import { DocumentEditPage } from "./documents/DocumentEditPage";
import { OnboardingPage } from "./onboarding/OnboardingPage";
import { BrowserSessionPage } from "./browser/BrowserSessionPage";
import { Tour } from "./tour/Tour";
import { getOnboarding, listPendingApprovals, updateOnboarding } from "./api/client";
import { ROUTES } from "./routes";

/**
 * A request to open a saved document for re-editing — fired when the user
 * clicks a document in the ledger. `source` is the saved CV HTML / cover-letter
 * text; `appId` is the application the re-save must update.
 */
export type EditRequest = {
  appId: string;
  kind: "cv" | "cover-letter";
  source: string;
};

/** Splash shown while the startup onboarding check is in flight. */
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

/** Blocking screen shown when the startup onboarding check fails. */
function BootError({ onRetry }: { onRetry: () => void }) {
  return (
    <Box
      className="shell shell--booting"
      role="alert"
      sx={{
        display: "flex",
        flexDirection: "column",
        alignItems: "center",
        justifyContent: "center",
        gap: 2,
      }}
    >
      <Typography variant="body1" sx={{ color: "text.secondary" }}>
        Can't reach the backend, so we can't tell whether setup is finished.
      </Typography>
      <Button variant="outlined" onClick={onRetry}>
        Retry
      </Button>
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

/** The app's top-level page routes. */
function TopLevelRoutes({ onOnboardingComplete }: { onOnboardingComplete: () => void }) {
  const navigate = useNavigate();
  const onBack = () => navigate(ROUTES.analytics);
  const onEditDocument = (req: EditRequest) =>
    navigate(ROUTES.documentEdit, { state: { editRequest: req } });

  return (
    <Routes>
      <Route path="/" element={<Navigate to={ROUTES.analytics} replace />} />
      <Route
        path={ROUTES.onboarding}
        element={<OnboardingPage onComplete={onOnboardingComplete} />}
      />
      <Route path={ROUTES.analytics} element={<AnalyticsPage onBack={onBack} />} />
      <Route
        path={ROUTES.applications}
        element={<ApplicationsPage onBack={onBack} onEditDocument={onEditDocument} />}
      />
      <Route
        path={ROUTES.filledForm}
        element={<FilledFormPage onBack={() => navigate(ROUTES.applications)} />}
      />
      <Route path={ROUTES.agents} element={<AgentsPage onBack={onBack} />} />
      <Route path={ROUTES.screenings} element={<ScreeningsPage onBack={onBack} />} />
      <Route path={ROUTES.approvals} element={<ApprovalsPage onBack={onBack} />} />
      <Route
        path={ROUTES.uploadCv}
        element={<UploadCvPage onDone={() => navigate(ROUTES.analytics)} />}
      />
      <Route path={ROUTES.documentEdit} element={<DocumentEditPage />} />
      <Route path={ROUTES.manual} element={<ManualPage />} />
      <Route path={ROUTES.browserSession} element={<BrowserSessionPage />} />
      <Route path="*" element={<Navigate to={ROUTES.analytics} replace />} />
    </Routes>
  );
}

/**
 * App shell. Every page is a real URL, so a browser refresh lands back on the
 * same page. A flat side nav replaces the old numbered wizard rail.
 */
export function App() {
  const { bootstrap, onboarding, setOnboarding, retryBootstrap } = useWizard();
  const [settingsOpen, setSettingsOpen] = useState(false);
  const location = useLocation();
  const navigate = useNavigate();
  const pendingApprovals = usePendingApprovalsBadge(location.pathname);

  if (bootstrap === "pending") return <BootSplash />;
  if (bootstrap === "error") return <BootError onRetry={retryBootstrap} />;

  // Gate every route but Onboarding itself until onboarding is complete.
  const onboardingIncomplete = onboarding !== null && !onboarding.complete;
  const showOnboardingGate =
    onboardingIncomplete && location.pathname !== ROUTES.onboarding;

  // Once onboarding is complete, show the guided tour exactly once.
  const showTour = onboarding !== null && onboarding.complete && !onboarding.tourSeenAt;

  // Both handlers navigate onward even if the server call fails — a
  // transient failure here must never strand the user on /onboarding or in
  // a tour that never ends.
  const finishOnboarding = async () => {
    try {
      setOnboarding(await getOnboarding());
    } catch (err) {
      console.error("Failed to refresh onboarding state", err);
      setOnboarding({
        providerDone: true,
        hasProfile: true,
        cvReviewedAt: new Date().toISOString(),
        tourSeenAt: null,
        complete: true,
      });
    }
    navigate(ROUTES.analytics);
  };

  const finishTour = async () => {
    try {
      setOnboarding(await updateOnboarding({ tourSeenAt: new Date().toISOString() }));
    } catch (err) {
      console.error("Failed to record tour completion", err);
      setOnboarding(
        onboarding && { ...onboarding, tourSeenAt: new Date().toISOString() },
      );
    }
    navigate(ROUTES.analytics);
  };

  return (
    <div className="shell">
      <SideNav
        pathname={location.pathname}
        onNavigate={navigate}
        onOpenSettings={() => setSettingsOpen(true)}
        pendingApprovals={pendingApprovals}
      />
      <main className="stage">
        <div className="stage__inner stage__inner--wide">
          {showOnboardingGate ? (
            <Navigate to={ROUTES.onboarding} replace />
          ) : (
            <TopLevelRoutes onOnboardingComplete={finishOnboarding} />
          )}
        </div>
      </main>

      {settingsOpen && <SettingsModal onClose={() => setSettingsOpen(false)} />}
      {showTour && <Tour onDone={finishTour} />}
    </div>
  );
}
