import { useState } from "react";
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
  completeClaudeLogin,
  logoutConnection,
  saveConnectionKey,
  startLogin,
} from "../api/client";
import { ButtonSpinner } from "../components/ButtonSpinner";
import { SettingsSection } from "./SettingsModal";
import type { ConnectionList, ConnectionStatus, StartLoginResult } from "../api/types";

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
  const dualMode = status.modes.includes("subscription") && status.modes.includes("apiKey");
  const [mode, setMode] = useState<string>(
    status.modes.includes("subscription") ? "subscription" : "apiKey",
  );
  const [error, setError] = useState<string | null>(null);

  // Subscription (paste-code) flow state.
  const [login, setLogin] = useState<StartLoginResult | null>(null);
  const [code, setCode] = useState("");
  const [connecting, setConnecting] = useState(false);
  const [confirming, setConfirming] = useState(false);

  // API key / URL entry state.
  const [apiKey, setApiKey] = useState("");
  const [baseUrl, setBaseUrl] = useState("");
  const [bearer, setBearer] = useState("");
  const [saving, setSaving] = useState(false);

  const [disconnecting, setDisconnecting] = useState(false);

  const isOllama = status.provider === "ollama";

  async function handleConnect() {
    setConnecting(true);
    setError(null);
    try {
      const result = await startLogin(status.provider);
      setLogin(result);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Couldn't start sign-in.");
    } finally {
      setConnecting(false);
    }
  }

  async function handleConfirmCode() {
    setConfirming(true);
    setError(null);
    try {
      await completeClaudeLogin(code);
      setCode("");
      setLogin(null);
      onChanged();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Couldn't complete sign-in.");
    } finally {
      setConfirming(false);
    }
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
  const showApiKey = mode === "apiKey" && status.modes.includes("apiKey");

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
              <ToggleButton value="apiKey">API key</ToggleButton>
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
                  {login.authUrl && (
                    <Link href={login.authUrl} target="_blank" rel="noreferrer">
                      Open Anthropic sign-in
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
                    placeholder={
                      status.apiKeyConnected ? "•••••  key saved" : "Optional"
                    }
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
                    onClick={() => handleDisconnect("apiKey")}
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
      {!list.encryptionAvailable && (
        <Alert severity="warning">
          Set <code>ENCRYPTION_KEY</code> in your <code>.env</code> to save
          keys securely. Until then TruthCV falls back to keys in the
          environment.
        </Alert>
      )}
      <Stack spacing={2}>
        {list.connections.map((status) => (
          <ConnectionCard key={status.provider} status={status} onChanged={onChanged} />
        ))}
      </Stack>
    </SettingsSection>
  );
}
