import { useState, useEffect, useRef } from "react";
import Box from "@mui/material/Box";
import Stack from "@mui/material/Stack";
import Card from "@mui/material/Card";
import CardContent from "@mui/material/CardContent";
import Button from "@mui/material/Button";
import Alert from "@mui/material/Alert";
import TextField from "@mui/material/TextField";
import Typography from "@mui/material/Typography";
import Link from "@mui/material/Link";
import ToggleButtonGroup from "@mui/material/ToggleButtonGroup";
import ToggleButton from "@mui/material/ToggleButton";
import {
  completeLogin,
  pollLogin,
  logoutConnection,
  saveConnectionKey,
  startLogin,
} from "../api/client";
import { ButtonSpinner } from "../components/ButtonSpinner";
import { SettingsSection } from "./SettingsModal";
import type { ConnectionList, ConnectionMode, ConnectionStatus, StartLoginResult } from "../api/types";

function statusLine(status: ConnectionStatus): string {
  const parts: string[] = [];
  if (status.subscriptionConnected) parts.push("Subscription connected");
  if (status.apiKeyConnected) parts.push("API key saved");
  return parts.length ? parts.join(" · ") : "Not connected";
}

/** A button that shows a spinner + busy label while an async handler runs.
 * Collapses the spinner/label/disabled pattern repeated by every action
 * button on a card. */
function AsyncButton({
  busy,
  busyLabel,
  label,
  onClick,
  disabled,
  variant = "contained",
}: {
  busy: boolean;
  busyLabel: string;
  label: string;
  onClick: () => void;
  disabled?: boolean;
  variant?: "contained" | "outlined";
}) {
  return (
    <Button variant={variant} onClick={onClick} disabled={busy || disabled}>
      {busy && <ButtonSpinner />}
      {busy ? busyLabel : label}
    </Button>
  );
}

/** One provider's card: mode toggle (for dual-mode providers), the
 * subscription paste-code flow, API key/URL entry, and per-mode disconnect. */
function ConnectionCard({
  status,
  onChanged,
}: {
  status: ConnectionStatus;
  onChanged: () => void;
}) {
  const dualMode = status.modes.includes("subscription") && status.modes.includes("apikey");
  const [mode, setMode] = useState<ConnectionMode>(
    status.modes.includes("subscription") ? "subscription" : status.modes[0],
  );
  const [error, setError] = useState<string | null>(null);

  // Subscription flow state (paste-code for claude, device-code for codex).
  const [login, setLogin] = useState<StartLoginResult | null>(null);
  const [code, setCode] = useState("");
  const [connecting, setConnecting] = useState(false);
  const [confirming, setConfirming] = useState(false);

  // Device-code polling state.
  const [polling, setPolling] = useState(false);
  const pollTimerRef = useRef<number | null>(null);
  const cancelledRef = useRef(false);

  // API key / URL entry state.
  const [apiKey, setApiKey] = useState("");
  const [baseUrl, setBaseUrl] = useState("");
  const [bearer, setBearer] = useState("");
  const [saving, setSaving] = useState(false);

  const [disconnecting, setDisconnecting] = useState(false);

  const isOllama = status.provider === "ollama";

  // Clean up polling timer on unmount.
  useEffect(() => {
    return () => {
      cancelledRef.current = true;
      if (pollTimerRef.current !== null) {
        clearTimeout(pollTimerRef.current);
      }
    };
  }, []);

  async function handleConnect() {
    setConnecting(true);
    setError(null);
    try {
      const result = await startLogin(status.provider);
      setLogin(result);
      // If device-code flow, start polling immediately.
      if (result.flow === "device-code") {
        cancelledRef.current = false;
        startPolling();
      }
    } catch (e) {
      setError(e instanceof Error ? e.message : "Couldn't start sign-in.");
    } finally {
      setConnecting(false);
    }
  }

  function startPolling() {
    setPolling(true);
    const poll = async () => {
      if (cancelledRef.current) return;
      try {
        const result = await pollLogin(status.provider);
        if (cancelledRef.current) return;
        if (result.status === "complete") {
          setPolling(false);
          setLogin(null);
          onChanged();
          return;
        }
        // Pending — use the returned interval if provided, otherwise fall back.
        const intervalMs = (result.intervalSeconds ?? login?.intervalSeconds ?? 5) * 1000;
        pollTimerRef.current = window.setTimeout(poll, intervalMs);
      } catch (e) {
        if (cancelledRef.current) return;
        setPolling(false);
        setError(e instanceof Error ? e.message : "Sign-in failed.");
        setLogin(null);
      }
    };
    poll();
  }

  async function handleConfirmCode() {
    setConfirming(true);
    setError(null);
    try {
      // For paste-code (claude), use completeClaudeLogin (alias to completeLogin).
      // For device-code (codex), this shouldn't be called — but guard anyway.
      await completeLogin(status.provider, code);
      setCode("");
      setLogin(null);
      onChanged();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Couldn't complete sign-in.");
    } finally {
      setConfirming(false);
    }
  }

  function handleCancelDeviceCode() {
    cancelledRef.current = true;
    if (pollTimerRef.current !== null) {
      clearTimeout(pollTimerRef.current);
      pollTimerRef.current = null;
    }
    setPolling(false);
    setLogin(null);
  }

  async function handleSaveKey() {
    setSaving(true);
    setError(null);
    try {
      const body = isOllama
        ? {
            baseUrl: baseUrl.trim() || undefined,
            bearer: bearer.trim() || undefined,
          }
        : { apiKey: apiKey.trim() || undefined };
      await saveConnectionKey(status.provider, body);
      setApiKey("");
      setBearer("");
      onChanged();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Couldn't save.");
    } finally {
      setSaving(false);
    }
  }

  async function handleDisconnect(disconnectMode: string) {
    setDisconnecting(true);
    setError(null);
    try {
      await logoutConnection(status.provider, disconnectMode);
      onChanged();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Couldn't disconnect.");
    } finally {
      setDisconnecting(false);
    }
  }

  const showSubscription = mode === "subscription" && status.modes.includes("subscription");
  const showApiKey =
    (mode === "apikey" && status.modes.includes("apikey")) ||
    (mode === "url" && status.modes.includes("url"));

  return (
    <Card variant="outlined">
      <CardContent>
        <Stack spacing={1.5}>
          <Stack spacing={0.25}>
            <Typography variant="subtitle1">{status.label}</Typography>
            <Typography variant="body2" color="text.secondary">
              {statusLine(status)}
            </Typography>
          </Stack>

          {dualMode && (
            <ToggleButtonGroup
              value={mode}
              exclusive
              size="small"
              onChange={(_e, next) => {
                if (next) {
                  setMode(next);
                  setError(null);
                }
              }}
            >
              <ToggleButton value="subscription">Subscription</ToggleButton>
              <ToggleButton value="apikey">API key</ToggleButton>
            </ToggleButtonGroup>
          )}

          {showSubscription && (
            <Stack spacing={1.5}>
              {status.subscriptionConnected ? (
                <AsyncButton
                  variant="outlined"
                  busy={disconnecting}
                  busyLabel="Disconnecting…"
                  label="Disconnect"
                  onClick={() => handleDisconnect("subscription")}
                />
              ) : login ? (
                <Stack spacing={1.5}>
                  {login.flow === "device-code" ? (
                    <>
                      <Typography variant="body1">
                        <strong>Enter this code:</strong>
                      </Typography>
                      <Typography
                        variant="h6"
                        sx={{ fontFamily: "monospace", letterSpacing: "0.2em" }}
                      >
                        {login.userCode}
                      </Typography>
                      <Typography variant="body2" color="text.secondary">
                        Then go to{" "}
                        <Link
                          href={login.verificationUri ?? undefined}
                          target="_blank"
                          rel="noreferrer"
                        >
                          {login.verificationUri}
                        </Link>
                        {" and type the code."}
                      </Typography>
                      <Typography variant="body2" color="text.secondary">
                        Polling every {login.intervalSeconds ?? 5}s…
                        {polling && " (waiting for sign-in)"}
                      </Typography>
                      {/* Deliberately NOT an AsyncButton: it must stay enabled while
                      polling is in flight — that is the whole point of
                      cancel, and a busy-disabled control could never be
                      clicked. */}
                      <Button variant="outlined" onClick={handleCancelDeviceCode}>
                        Cancel
                      </Button>
                    </>
                  ) : (
                    <>
                      {login.authUrl && (
                        <Link href={login.authUrl} target="_blank" rel="noreferrer">
                          Open {status.label} sign-in
                        </Link>
                      )}
                      <TextField
                        label="Code"
                        value={code}
                        onChange={(e) => setCode(e.target.value)}
                        placeholder="code#state"
                        autoComplete="off"
                      />
                      <AsyncButton
                        busy={confirming}
                        busyLabel="Confirming…"
                        label="Confirm"
                        onClick={handleConfirmCode}
                        disabled={!code.trim()}
                      />
                    </>
                  )}
                </Stack>
              ) : (
                <AsyncButton
                  busy={connecting}
                  busyLabel="Connecting…"
                  label="Connect"
                  onClick={handleConnect}
                />
              )}
            </Stack>
          )}

          {showApiKey && (
            <Stack spacing={1.5}>
              {isOllama ? (
                <>
                  <TextField
                    label="Base URL"
                    type="text"
                    value={baseUrl}
                    onChange={(e) => setBaseUrl(e.target.value)}
                    placeholder="http://localhost:11434"
                  />
                  <TextField
                    label="Bearer token (optional)"
                    type="password"
                    autoComplete="off"
                    value={bearer}
                    onChange={(e) => setBearer(e.target.value)}
                    placeholder="Optional"
                  />
                </>
              ) : (
                <TextField
                  label="API key"
                  type="password"
                  autoComplete="off"
                  value={apiKey}
                  onChange={(e) => setApiKey(e.target.value)}
                  placeholder={
                    status.apiKeyConnected ? "•••••  key saved" : "Paste your API key"
                  }
                  helperText={
                    status.apiKeyConnected
                      ? "A key is saved. Leave blank to keep it, or type a new one to replace it."
                      : "Stored encrypted on the server — never sent back to the browser."
                  }
                />
              )}
              <Box>
                <AsyncButton busy={saving} busyLabel="Saving…" label="Save" onClick={handleSaveKey} />
              </Box>
              {status.apiKeyConnected && (
                <Box>
                  <AsyncButton
                    variant="outlined"
                    busy={disconnecting}
                    busyLabel="Disconnecting…"
                    label="Disconnect"
                    onClick={() => handleDisconnect("apikey")}
                  />
                </Box>
              )}
            </Stack>
          )}

          {error && <Alert severity="error">{error}</Alert>}
        </Stack>
      </CardContent>
    </Card>
  );
}

/** Provider accounts section: one card per connection, each managing its own
 * subscription/API-key flow and errors. `onChanged` re-fetches the parent's
 * connection list after any mutating action so cards reflect fresh status. */
export function AccountsSection({
  list,
  onChanged,
}: {
  list: ConnectionList;
  onChanged: () => void;
}) {
  return (
    <SettingsSection
      title="Accounts"
      description="Connect the providers TruthCV and the application agent use."
    >
      <Stack spacing={2}>
        {list.connections.map((status) => (
          <ConnectionCard key={status.provider} status={status} onChanged={onChanged} />
        ))}
      </Stack>
    </SettingsSection>
  );
}
