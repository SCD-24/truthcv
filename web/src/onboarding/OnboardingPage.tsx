import { useEffect, useState } from "react";
import Stack from "@mui/material/Stack";
import Typography from "@mui/material/Typography";
import Alert from "@mui/material/Alert";
import { getOnboarding, getRouting, listConnections } from "../api/client";
import { SettingsSection } from "../settings/SettingsModal";
import { AccountsSection } from "../settings/AccountsSection";
import { DefaultModelSection } from "../settings/DefaultModelSection";
import { UploadReviewFlow } from "../cv/UploadCvPage";
import type { ConnectionList, Routing } from "../api/types";

/** The ordered setup steps this page can walk through. Steps whose work is
 * already done on the server are dropped up front, never rendered. */
type Step = "provider" | "cv";

/**
 * First-run onboarding: a linear, UNNUMBERED setup flow (no "step N of M"
 * wizard chrome) that walks the user through the minimum needed to use the
 * app, skipping straight past anything already satisfied on the server.
 *
 * On mount it fetches the connection list, routing, and onboarding state
 * (the same pair {@link SettingsModal} loads, plus onboarding progress) and
 * builds the list of steps still to do:
 *   1. "Connect a provider" — skipped when `routing.default` is already set
 *      (mirrors the server's `providerDone`).
 *   2 + 3. "Upload your CV" then "Review" — one combined {@link UploadReviewFlow}
 *      whose own internal split provides the two steps; skipped when the
 *      onboarding state already has `cvReviewedAt`.
 *
 * When every step is already satisfied (or once the last one completes) it
 * calls `onComplete` — the hand-off point to a later "tour" feature.
 */
export function OnboardingPage({ onComplete }: { onComplete: () => void }) {
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [connections, setConnections] = useState<ConnectionList | null>(null);
  const [routing, setRouting] = useState<Routing | null>(null);
  const [steps, setSteps] = useState<Step[]>([]);
  const [index, setIndex] = useState(0);
  const [hasProfile, setHasProfile] = useState(false);

  // Load everything the flow decides on, then compute which steps remain.
  useEffect(() => {
    let alive = true;
    Promise.all([listConnections(), getRouting(), getOnboarding()])
      .then(([c, r, o]) => {
        if (!alive) return;
        setConnections(c);
        setRouting(r);
        setHasProfile(o.hasProfile);
        const pending: Step[] = [];
        if (r.default == null) pending.push("provider");
        if (o.cvReviewedAt == null) pending.push("cv");
        setSteps(pending);
        if (pending.length === 0) onComplete();
      })
      .catch((e: unknown) =>
        alive && setError(e instanceof Error ? e.message : "Couldn't start setup."),
      )
      .finally(() => alive && setLoading(false));
    return () => {
      alive = false;
    };
    // Run once on mount; onComplete is a stable hand-off callback.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // Move to the next remaining step; hand off once we walk past the last one.
  const advance = () => {
    const next = index + 1;
    setIndex(next);
    if (next >= steps.length) onComplete();
  };

  function refetchConnections() {
    listConnections()
      .then(setConnections)
      .catch((e: unknown) =>
        setError(e instanceof Error ? e.message : "Couldn't load connections."),
      );
  }

  // Saving the default routing advances past the provider step the moment a
  // default becomes set (matching the server's `providerDone`).
  function onRoutingSaved(r: Routing) {
    setRouting(r);
    if (r.default != null) advance();
  }

  if (loading) {
    return (
      <Typography color="text.secondary" sx={{ py: 2 }}>
        Loading…
      </Typography>
    );
  }

  const current = steps[index];

  if (current === "provider" && connections && routing) {
    return (
      <SettingsSection
        title="Connect a provider"
        description="TruthCV needs a model provider to read your CV and tailor applications. Connect one and pick a default model to continue."
      >
        {error && <Alert severity="error">{error}</Alert>}
        <Stack spacing={3}>
          <AccountsSection list={connections} onChanged={refetchConnections} />
          <DefaultModelSection
            connections={connections.connections}
            routing={routing}
            onSaved={onRoutingSaved}
          />
        </Stack>
      </SettingsSection>
    );
  }

  if (current === "cv") {
    return (
      <UploadReviewFlow onDone={advance} initialPhase={hasProfile ? "review" : "upload"} />
    );
  }

  // All steps done (onComplete already called) — nothing left to render.
  return null;
}
