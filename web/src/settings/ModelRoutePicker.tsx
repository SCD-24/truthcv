import { useEffect, useState } from "react";
import Box from "@mui/material/Box";
import Stack from "@mui/material/Stack";
import Button from "@mui/material/Button";
import Alert from "@mui/material/Alert";
import TextField from "@mui/material/TextField";
import MenuItem from "@mui/material/MenuItem";
import InputAdornment from "@mui/material/InputAdornment";
import { listConnectionModels, testConnectionProvider } from "../api/client";
import { ButtonSpinner } from "../components/ButtonSpinner";
import { SettingsSection } from "./SettingsModal";
import type { ConnectionStatus, ModelInfo, RouteChoice } from "../api/types";

/** Sentinel select value that reveals the free-text model field. Mirrors the
 * pattern the old provider panel used for its model field. */
const CUSTOM_MODEL = "__custom__";

type TestState =
  | { kind: "idle" }
  | { kind: "testing" }
  | { kind: "ok"; detail: string }
  | { kind: "fail"; detail: string };

/** A provider connection is usable for routing once either its subscription
 * or its API key is connected. */
function isConnected(status: ConnectionStatus): boolean {
  return status.subscriptionConnected || status.apiKeyConnected;
}

/** Shared connection + model picker: pick a connected provider, pick (or
 * type) a model, save it as a routing choice, optionally test it or clear
 * it. Used directly by any section that needs "which model runs for X". */
export function ModelRoutePicker({
  connections,
  route,
  onSave,
  title,
  description,
  saveLabel = "Save",
  savedLabel = "Saved.",
  filterCards,
  allowClear = false,
  showTest = false,
}: {
  connections: ConnectionStatus[];
  route: RouteChoice | null;
  onSave: (route: RouteChoice | null) => Promise<void>;
  title: string;
  description?: string;
  saveLabel?: string;
  savedLabel?: string;
  filterCards?: string[];
  allowClear?: boolean;
  showTest?: boolean;
}) {
  const connectedConnections = connections
    .filter(isConnected)
    .filter((c) => !filterCards || filterCards.includes(c.provider));
  const connectedKey = connectedConnections.map((c) => c.provider).join(" ");

  const [connection, setConnection] = useState(
    route?.connection ?? connectedConnections[0]?.provider ?? "",
  );
  const [model, setModel] = useState(route?.model ?? "");
  const [customModel, setCustomModel] = useState(false);
  const [models, setModels] = useState<ModelInfo[]>([]);
  const [modelsLoading, setModelsLoading] = useState(false);
  const [modelsError, setModelsError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);
  const [saved, setSaved] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [test, setTest] = useState<TestState>({ kind: "idle" });

  // Pull the connection's model list live. Returns the list so callers can
  // decide whether the current model is a known option or a custom id.
  async function loadModels(conn: string): Promise<ModelInfo[]> {
    if (!conn) {
      setModels([]);
      return [];
    }
    setModelsLoading(true);
    setModelsError(null);
    try {
      const list = (await listConnectionModels(conn)) ?? [];
      setModels(list);
      return list;
    } catch (e) {
      setModels([]);
      setModelsError(e instanceof Error ? e.message : "Couldn't load models.");
      return [];
    } finally {
      setModelsLoading(false);
    }
  }

  // Reconcile the selected connection against the live connected set: a
  // saved default may point at a card that was disconnected before this
  // panel was ever opened, or a card connected when it opened may be
  // disconnected live via AccountsSection while it's still showing. Either
  // way a selection that isn't in the connected set is stale — fall back to
  // the first still-connected card, or none, and drop its stale model choice
  // so Save can't re-persist an invalid default.
  useEffect(() => {
    const stillValid = connectedConnections.some((c) => c.provider === connection);
    if (stillValid) return;
    const next = connectedConnections[0]?.provider ?? "";
    if (next === connection) return;
    setConnection(next);
    setModel("");
    setCustomModel(false);
    setModels([]);
    setTest({ kind: "idle" });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [connectedKey]);

  // Load the selected connection's models whenever it changes — including on
  // mount, after a manual connection pick, and after the reconciliation
  // effect above corrects a stale selection — and mark the current model as
  // custom if it isn't in the live list (so it survives even if the list
  // can't be fetched). Skipped for a connection not currently in the
  // connected set: the reconciliation effect is about to replace it, and
  // fetching models for a disconnected card would be wasted (or fail).
  useEffect(() => {
    if (!connection || !connectedConnections.some((c) => c.provider === connection)) {
      setModels([]);
      return;
    }
    let alive = true;
    loadModels(connection).then((list) => {
      if (!alive) return;
      setCustomModel(!!model && !list.some((m) => m.id === model));
    });
    return () => {
      alive = false;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [connection, connectedKey]);

  async function handleSave() {
    setSaving(true);
    setError(null);
    setSaved(false);
    try {
      await onSave({ connection, model });
      setSaved(true);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Couldn't save routing.");
    } finally {
      setSaving(false);
    }
  }

  async function handleClear() {
    setSaving(true);
    setError(null);
    setSaved(false);
    try {
      await onSave(null);
      setSaved(true);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Couldn't save routing.");
    } finally {
      setSaving(false);
    }
  }

  async function handleTest() {
    setTest({ kind: "testing" });
    try {
      const res = await testConnectionProvider(connection, model);
      setTest(
        res.ok
          ? { kind: "ok", detail: res.detail || "Connected." }
          : { kind: "fail", detail: res.detail || "Couldn't connect." },
      );
    } catch (e) {
      setTest({
        kind: "fail",
        detail: e instanceof Error ? e.message : "Couldn't connect.",
      });
    }
  }

  return (
    <SettingsSection title={title} description={description}>
      <TextField
        select
        label="Connection"
        value={connection}
        onChange={(e) => {
          const next = e.target.value;
          setConnection(next);
          setModel("");
          setCustomModel(false);
          setTest({ kind: "idle" });
        }}
      >
        {connectedConnections.map((c) => (
          <MenuItem key={c.provider} value={c.provider}>
            {c.label}
          </MenuItem>
        ))}
      </TextField>

      <Box>
        <TextField
          select
          fullWidth
          label="Model"
          value={customModel ? CUSTOM_MODEL : model}
          onChange={(e) => {
            const v = e.target.value;
            if (v === CUSTOM_MODEL) {
              setCustomModel(true);
              setModel("");
            } else {
              setCustomModel(false);
              setModel(v);
            }
          }}
          slotProps={{
            input: {
              endAdornment: (
                <InputAdornment position="end" sx={{ mr: 2 }}>
                  <Button
                    size="small"
                    onClick={() => loadModels(connection)}
                    disabled={modelsLoading || !connection}
                  >
                    {modelsLoading && <ButtonSpinner size={12} />}
                    {modelsLoading ? "Loading…" : "Reload"}
                  </Button>
                </InputAdornment>
              ),
            },
          }}
          helperText={
            modelsError
              ? `${modelsError} You can still pick Custom or reload.`
              : "Pulled live from the connection. Blank uses its default; choose Custom for an id not listed."
          }
        >
          <MenuItem value="">Provider default</MenuItem>
          {models.map((m) => (
            <MenuItem key={m.id} value={m.id}>
              {m.label}
            </MenuItem>
          ))}
          <MenuItem value={CUSTOM_MODEL}>Custom…</MenuItem>
        </TextField>
        {customModel && (
          <TextField
            fullWidth
            type="text"
            value={model}
            // eslint-disable-next-line jsx-a11y/no-autofocus
            autoFocus
            onChange={(e) => setModel(e.target.value)}
            placeholder="Exact model id"
            aria-label="Custom model id"
            sx={{ mt: 1.5 }}
          />
        )}
      </Box>

      {test.kind === "ok" && <Alert severity="success">{test.detail}</Alert>}
      {test.kind === "fail" && <Alert severity="error">{test.detail}</Alert>}
      {error && <Alert severity="error">{error}</Alert>}
      {saved && !error && <Alert severity="success">{savedLabel}</Alert>}

      <Stack direction="row" spacing={2}>
        {showTest && (
          <Button
            variant="outlined"
            onClick={handleTest}
            disabled={!connection || test.kind === "testing"}
          >
            {test.kind === "testing" && <ButtonSpinner />}
            {test.kind === "testing" ? "Testing…" : "Test connection"}
          </Button>
        )}
        {allowClear && (
          <Button variant="outlined" onClick={handleClear} disabled={saving}>
            Clear
          </Button>
        )}
        <Button variant="contained" onClick={handleSave} disabled={!connection || saving}>
          {saving ? "Saving…" : saveLabel}
        </Button>
      </Stack>
    </SettingsSection>
  );
}
