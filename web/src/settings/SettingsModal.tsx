import { useEffect, useState } from "react";
import Dialog from "@mui/material/Dialog";
import DialogTitle from "@mui/material/DialogTitle";
import DialogContent from "@mui/material/DialogContent";
import DialogActions from "@mui/material/DialogActions";
import Box from "@mui/material/Box";
import Stack from "@mui/material/Stack";
import Button from "@mui/material/Button";
import IconButton from "@mui/material/IconButton";
import CloseIcon from "@mui/icons-material/Close";
import Alert from "@mui/material/Alert";
import TextField from "@mui/material/TextField";
import MenuItem from "@mui/material/MenuItem";
import InputAdornment from "@mui/material/InputAdornment";
import Typography from "@mui/material/Typography";
import {
  getSettings,
  listModels,
  saveSettings,
  testConnection,
} from "../api/client";
import type {
  ModelInfo,
  ProviderName,
  SettingsStatus,
  SettingsUpdate,
} from "../api/types";
import "../styles/settings.css";

const PROVIDERS: { id: ProviderName; label: string }[] = [
  { id: "anthropic", label: "Anthropic" },
  { id: "openai", label: "OpenAI" },
  { id: "ollama", label: "Ollama" },
];

/** Sentinel select value that reveals the free-text model field. */
const CUSTOM_MODEL = "__custom__";

/** Is this provider one that authenticates with an API key (vs. a local host)? */
function usesApiKey(provider: string): boolean {
  return provider === "anthropic" || provider === "openai";
}

/** Whether the currently-selected provider already has a key saved server-side. */
function keyIsSet(status: SettingsStatus | null, provider: string): boolean {
  if (!status) return false;
  if (provider === "anthropic") return status.anthropicKeySet;
  if (provider === "openai") return status.openaiKeySet;
  return false;
}

type TestState =
  | { kind: "idle" }
  | { kind: "testing" }
  | { kind: "ok"; detail: string }
  | { kind: "fail"; detail: string };

/**
 * The provider settings modal, opened from the rail's Settings control. Reads current status
 * (secrets are never sent back — the API only reports whether a key is set),
 * lets the user pick the active provider, enter a key (blank leaves it as is),
 * set an optional model, test the connection, and save. Encrypted at rest by
 * the backend via ENCRYPTION_KEY.
 */
export function SettingsModal({ onClose }: { onClose: () => void }) {
  const [status, setStatus] = useState<SettingsStatus | null>(null);
  const [provider, setProvider] = useState<string>("anthropic");
  const [apiKey, setApiKey] = useState("");
  const [model, setModel] = useState("");
  const [customModel, setCustomModel] = useState(false);
  const [models, setModels] = useState<ModelInfo[]>([]);
  const [modelsLoading, setModelsLoading] = useState(false);
  const [modelsError, setModelsError] = useState<string | null>(null);
  const [ollamaHost, setOllamaHost] = useState("");
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [saved, setSaved] = useState(false);
  const [test, setTest] = useState<TestState>({ kind: "idle" });

  // Pull the provider's model list live (uses a typed-but-unsaved key/host if
  // present, else the saved credential). Returns the list so callers can decide
  // whether the current model is a known option or a custom id.
  async function loadModels(
    prov: string,
    key: string,
    host: string,
  ): Promise<ModelInfo[]> {
    setModelsLoading(true);
    setModelsError(null);
    try {
      const list = await listModels({
        activeProvider: prov,
        apiKey: key.trim() || undefined,
        ollamaHost: host.trim() || undefined,
      });
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

  // Load current status once when the modal opens.
  useEffect(() => {
    let alive = true;
    getSettings()
      .then((s) => {
        if (!alive) return;
        const prov = s.activeProvider || "anthropic";
        setStatus(s);
        setProvider(prov);
        setModel(s.model || "");
        setOllamaHost(s.ollamaHost || "");
        // A saved model that isn't in the live list is treated as custom (so it
        // survives even if the list can't be fetched — e.g. no key yet).
        loadModels(prov, "", s.ollamaHost || "").then((list) => {
          if (!alive) return;
          setCustomModel(!!s.model && !list.some((m) => m.id === s.model));
        });
      })
      .catch((e: unknown) =>
        setError(e instanceof Error ? e.message : "Couldn't load settings."),
      )
      .finally(() => alive && setLoading(false));
    return () => {
      alive = false;
    };
  }, []);

  function buildUpdate(): SettingsUpdate {
    const body: SettingsUpdate = { activeProvider: provider };
    if (model.trim()) body.model = model.trim();
    if (usesApiKey(provider)) {
      if (apiKey.trim()) body.apiKey = apiKey.trim();
    } else {
      if (ollamaHost.trim()) body.ollamaHost = ollamaHost.trim();
    }
    return body;
  }

  async function handleSave() {
    setSaving(true);
    setError(null);
    setSaved(false);
    try {
      const fresh = await saveSettings(buildUpdate());
      setStatus(fresh);
      setApiKey(""); // never keep the raw key around after saving
      setSaved(true);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Couldn't save settings.");
    } finally {
      setSaving(false);
    }
  }

  async function handleTest() {
    setTest({ kind: "testing" });
    try {
      const res = await testConnection(buildUpdate());
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

  const encryptionOff = status ? !status.encryptionAvailable : false;
  const keySet = keyIsSet(status, provider);

  return (
    <Dialog open onClose={onClose} maxWidth="sm" fullWidth aria-labelledby="settings-title">
      <DialogTitle
        id="settings-title"
        sx={{ display: "flex", alignItems: "center", justifyContent: "space-between" }}
      >
        Provider settings
        <IconButton onClick={onClose} aria-label="Close settings" edge="end">
          <CloseIcon />
        </IconButton>
      </DialogTitle>

      <DialogContent dividers>
        {loading ? (
          <Typography color="text.secondary" sx={{ py: 2 }}>
            Loading settings…
          </Typography>
        ) : (
          <Stack spacing={2}>
            {encryptionOff && (
              <Alert severity="warning">
                Set <code>ENCRYPTION_KEY</code> in your <code>.env</code> to save
                keys securely. Until then TruthCV falls back to keys in the
                environment.
              </Alert>
            )}

            <TextField
              select
              label="Provider"
              value={provider}
              onChange={(e) => {
                const next = e.target.value;
                setProvider(next);
                setApiKey("");
                // A model from one provider doesn't apply to another —
                // fall back to that provider's default and reload the list.
                setModel("");
                setCustomModel(false);
                setTest({ kind: "idle" });
                loadModels(next, "", ollamaHost);
              }}
            >
              {PROVIDERS.map((p) => (
                <MenuItem key={p.id} value={p.id}>
                  {p.label}
                </MenuItem>
              ))}
            </TextField>

            {usesApiKey(provider) ? (
              <TextField
                label="API key"
                type="password"
                autoComplete="off"
                value={apiKey}
                onChange={(e) => setApiKey(e.target.value)}
                placeholder={keySet ? "•••••  key saved" : "Paste your API key"}
                disabled={encryptionOff && !keySet}
                helperText={
                  keySet
                    ? "A key is saved. Leave blank to keep it, or type a new one to replace it."
                    : "Stored encrypted on the server — never sent back to the browser."
                }
              />
            ) : (
              <TextField
                label="Host"
                type="text"
                value={ollamaHost}
                onChange={(e) => setOllamaHost(e.target.value)}
                placeholder="http://localhost:11434"
                helperText="Where your local Ollama server is running."
              />
            )}

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
                          onClick={() => loadModels(provider, apiKey, ollamaHost)}
                          disabled={modelsLoading}
                        >
                          {modelsLoading ? "Loading…" : "Reload"}
                        </Button>
                      </InputAdornment>
                    ),
                  },
                }}
                helperText={
                  modelsError
                    ? `${modelsError} You can still pick Custom or enter a key and reload.`
                    : "Pulled live from the provider. Blank uses its default; choose Custom for an id not listed."
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
                  placeholder={
                    provider === "ollama"
                      ? "e.g. llama3.2:latest"
                      : "Exact model id"
                  }
                  aria-label="Custom model id"
                  sx={{ mt: 1.5 }}
                />
              )}
            </Box>

            {test.kind === "ok" && <Alert severity="success">{test.detail}</Alert>}
            {test.kind === "fail" && <Alert severity="error">{test.detail}</Alert>}
            {error && <Alert severity="error">{error}</Alert>}
            {saved && !error && <Alert severity="success">Settings saved.</Alert>}
          </Stack>
        )}
      </DialogContent>

      <DialogActions>
        <Button
          variant="outlined"
          onClick={handleTest}
          disabled={loading || test.kind === "testing"}
        >
          {test.kind === "testing" ? "Testing…" : "Test connection"}
        </Button>
        <Button
          variant="contained"
          onClick={handleSave}
          disabled={loading || saving}
        >
          {saving ? "Saving…" : "Save"}
        </Button>
      </DialogActions>
    </Dialog>
  );
}
