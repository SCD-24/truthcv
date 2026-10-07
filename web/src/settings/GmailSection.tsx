import { useEffect, useRef, useState } from "react";
import Alert from "@mui/material/Alert";
import Box from "@mui/material/Box";
import Button from "@mui/material/Button";
import Checkbox from "@mui/material/Checkbox";
import FormControlLabel from "@mui/material/FormControlLabel";
import FormHelperText from "@mui/material/FormHelperText";
import Typography from "@mui/material/Typography";
import {
  dismissGmailSuggestions,
  listGmailSuggestions,
  getGmailStatus,
  getJevSettings,
  saveJevSettings,
  startGmailLogin,
  syncGmailResponses,
} from "../api/client";
import { ButtonSpinner } from "../components/ButtonSpinner";
import { SettingsSection } from "./SettingsModal";
import { GmailSuggestionsList, PAGE_SIZE } from "./GmailSuggestionsList";
import type {
  GmailStatus,
  GmailSuggestion,
  GmailSyncSummary,
  JevSettings,
} from "../api/types";

/** Gmail response tracking: reads Gmail for replies to submitted
 * applications and (when Jev confirms a transition) auto-applies it. Locked
 * behind the same Jev API key as screening cross-checks — Gmail sync
 * auto-applies Jev-confirmed transitions, so it must never run without an
 * explicit opt-in on top of a saved key. */
export function GmailSection() {
  const [jev, setJev] = useState<JevSettings | null>(null);
  const [gmail, setGmail] = useState<GmailStatus | null>(null);
  const [toggling, setToggling] = useState(false);
  const [connecting, setConnecting] = useState(false);
  const [syncing, setSyncing] = useState(false);
  const [syncResult, setSyncResult] = useState<GmailSyncSummary | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [suggestions, setSuggestions] = useState<GmailSuggestion[]>([]);
  const [total, setTotal] = useState(0);
  const [page, setPage] = useState(0);
  const [pendingIds, setPendingIds] = useState<string[]>([]);
  const [announcement, setAnnouncement] = useState("");

  // Mirrors the backend gate: saved Jev key AND opt-in (plus a connection).
  const trackingOn = !!(gmail?.connected && jev?.keySet && jev?.useForEmailTracking);
  const loadSeq = useRef(0);
  const mounted = useRef(true);

  useEffect(() => {
    mounted.current = true;
    return () => {
      mounted.current = false;
    };
  }, []);

  async function loadPage(p: number) {
    const seq = ++loadSeq.current;
    try {
      const res = await listGmailSuggestions(PAGE_SIZE, p * PAGE_SIZE);
      if (!mounted.current || seq !== loadSeq.current) return;
      setSuggestions(res.items);
      setTotal(res.total);
      setPage(p);
    } catch (e) {
      if (!mounted.current || seq !== loadSeq.current) return;
      setError(e instanceof Error ? e.message : "Couldn't load suggestions.");
    }
  }

  useEffect(() => {
    if (trackingOn) void loadPage(0);
  }, [trackingOn]);

  async function handleDismiss(ids: string[]) {
    setPendingIds(ids);
    setError(null);
    try {
      const res = await dismissGmailSuggestions(ids);
      setAnnouncement(`Dismissed ${res.dismissed} suggestion${res.dismissed === 1 ? "" : "s"}`);
      let target = page;
      if (page > 0 && page * PAGE_SIZE >= res.pending) {
        target = Math.max(0, Math.ceil(res.pending / PAGE_SIZE) - 1);
      }
      await loadPage(target);
    } catch (e) {
      if (!mounted.current) return;
      setError(e instanceof Error ? e.message : "Couldn't dismiss suggestions.");
    } finally {
      if (mounted.current) setPendingIds([]);
    }
  }

  useEffect(() => {
    let alive = true;
    Promise.all([getJevSettings(), getGmailStatus()])
      .then(([j, g]) => {
        if (!alive) return;
        setJev(j);
        setGmail(g);
      })
      .catch((e: unknown) =>
        setError(e instanceof Error ? e.message : "Couldn't load Gmail settings."),
      );
    return () => {
      alive = false;
    };
  }, []);

  useEffect(() => {
    const params = new URLSearchParams(window.location.search);
    const gmailError = params.get("gmailError");
    if (!gmailError) return;
    // Map the callback's machine codes to fixed copy; anything else (or a
    // crafted link) falls back to a generic message rather than rendering
    // arbitrary query text as our own error copy.
    const known: Record<string, string> = {
      access_denied: "Gmail access was declined on the Google consent screen.",
      missing_code: "Google returned no authorization code — try connecting again.",
      auth_failed: "The Gmail sign-in could not be completed — try connecting again.",
      not_enabled: "Email response tracking was turned off before the sign-in finished.",
    };
    setError(known[gmailError] ?? "The Gmail connection failed — try connecting again.");
    params.delete("gmailError");
    const query = params.toString();
    window.history.replaceState(
      null,
      "",
      window.location.pathname + (query ? `?${query}` : "") + window.location.hash,
    );
  }, []);

  async function handleToggle(checked: boolean) {
    if (!jev?.keySet) return;
    setToggling(true);
    setError(null);
    try {
      const next = await saveJevSettings({ useForEmailTracking: checked });
      setJev(next);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Couldn't save the setting.");
    } finally {
      setToggling(false);
    }
  }

  async function handleConnect() {
    setConnecting(true);
    setError(null);
    try {
      const { authUrl } = await startGmailLogin();
      window.location.href = authUrl;
    } catch (e) {
      setError(e instanceof Error ? e.message : "Couldn't start the Gmail connection.");
      setConnecting(false);
    }
  }

  async function handleSync() {
    setSyncing(true);
    setError(null);
    setSyncResult(null);
    try {
      const summary = await syncGmailResponses();
      setSyncResult(summary);
      await loadPage(0);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Couldn't sync Gmail responses.");
    } finally {
      setSyncing(false);
    }
  }

  if (!jev || !gmail) {
    return (
      <SettingsSection
        title="Gmail"
        description="Track replies to submitted applications by reading Gmail."
      >
        {error ? (
          <Alert severity="error">{error}</Alert>
        ) : (
          <Typography color="text.secondary">Loading…</Typography>
        )}
      </SettingsSection>
    );
  }

  if (!jev.keySet) {
    return (
      <SettingsSection
        title="Gmail"
        description="Track replies to submitted applications by reading Gmail."
      >
        {error && <Alert severity="error">{error}</Alert>}
        <Typography color="text.secondary">
          Save a Jev API key above first — Gmail response tracking auto-applies
          Jev-confirmed transitions, so it stays locked until a key is saved.
        </Typography>
      </SettingsSection>
    );
  }

  return (
    <SettingsSection
      title="Gmail"
      description="Track replies to submitted applications by reading Gmail."
    >
      {error && <Alert severity="error">{error}</Alert>}
      <Box>
        <FormControlLabel
          control={
            <Checkbox
              checked={jev.useForEmailTracking}
              disabled={toggling}
              onChange={(e) => handleToggle(e.target.checked)}
            />
          }
          label="Enable email response tracking"
        />
        <FormHelperText>
          Gmail sync auto-applies Jev-confirmed transitions when this is on.
        </FormHelperText>
      </Box>

      {gmail.connected && gmail.email && (
        <Typography color="text.secondary">Connected as {gmail.email}</Typography>
      )}

      {gmail.reauthRequired && (
        <Alert severity="warning">
          Gmail needs to be reconnected — its access has expired or was revoked.
        </Alert>
      )}

      <Button
        variant="contained"
        onClick={handleConnect}
        disabled={!jev.useForEmailTracking || connecting}
        sx={{ alignSelf: "flex-start" }}
      >
        {connecting && <ButtonSpinner />}
        {connecting
          ? "Connecting…"
          : gmail.reauthRequired
            ? "Reconnect Gmail"
            : gmail.connected
              ? "Reconnect Gmail"
              : "Connect Gmail"}
      </Button>

      {gmail.connected && (
        <Button
          variant="outlined"
          onClick={handleSync}
          disabled={!jev.useForEmailTracking || syncing}
          sx={{ alignSelf: "flex-start" }}
        >
          {syncing && <ButtonSpinner />}
          {syncing ? "Syncing…" : "Sync now"}
        </Button>
      )}

      {gmail.connected && syncResult && (
        <Typography color="text.secondary">
          Scanned {syncResult.processed} new messages — {syncResult.suggestions} suggestions pending
        </Typography>
      )}

      {trackingOn && (
        <GmailSuggestionsList
          items={suggestions}
          total={total}
          page={page}
          pendingIds={pendingIds}
          bulkBusy={pendingIds.length > 0}
          announcement={announcement}
          onPageChange={(p) => void loadPage(p)}
          onDismiss={(ids) => void handleDismiss(ids)}
        />
      )}
    </SettingsSection>
  );
}
