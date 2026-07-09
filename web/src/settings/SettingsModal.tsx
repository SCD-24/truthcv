import { useEffect, useRef, useState } from "react";
import {
  getSettings,
  saveSettings,
  testConnection,
} from "../api/client";
import type {
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
 * The provider settings modal, opened from the footer. Reads current status
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
  const [ollamaHost, setOllamaHost] = useState("");
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [saved, setSaved] = useState(false);
  const [test, setTest] = useState<TestState>({ kind: "idle" });

  const dialogRef = useRef<HTMLDivElement>(null);

  // Load current status once when the modal opens.
  useEffect(() => {
    let alive = true;
    getSettings()
      .then((s) => {
        if (!alive) return;
        setStatus(s);
        setProvider(s.activeProvider || "anthropic");
        setModel(s.model || "");
        setOllamaHost(s.ollamaHost || "");
      })
      .catch((e: unknown) =>
        setError(e instanceof Error ? e.message : "Couldn't load settings."),
      )
      .finally(() => alive && setLoading(false));
    return () => {
      alive = false;
    };
  }, []);

  // Close on Escape; trap initial focus into the dialog.
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
    };
    document.addEventListener("keydown", onKey);
    dialogRef.current?.querySelector<HTMLElement>("select,input,button")?.focus();
    return () => document.removeEventListener("keydown", onKey);
  }, [onClose]);

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
    <div
      className="modal__scrim"
      onMouseDown={(e) => {
        if (e.target === e.currentTarget) onClose();
      }}
    >
      <div
        className="modal"
        role="dialog"
        aria-modal="true"
        aria-labelledby="settings-title"
        ref={dialogRef}
      >
        <header className="modal__head">
          <h2 id="settings-title" className="modal__title">
            Provider settings
          </h2>
          <button
            type="button"
            className="modal__close"
            onClick={onClose}
            aria-label="Close settings"
          >
            ×
          </button>
        </header>

        {loading ? (
          <p className="modal__body modal__loading">Loading settings…</p>
        ) : (
          <div className="modal__body">
            {encryptionOff && (
              <p className="notice notice--warn" role="status">
                Set <code>ENCRYPTION_KEY</code> in your <code>.env</code> to save
                keys securely. Until then TruthCV falls back to keys in the
                environment.
              </p>
            )}

            <label className="field">
              <span className="field__label">Provider</span>
              <select
                className="input"
                value={provider}
                onChange={(e) => {
                  setProvider(e.target.value);
                  setApiKey("");
                  setTest({ kind: "idle" });
                }}
              >
                {PROVIDERS.map((p) => (
                  <option key={p.id} value={p.id}>
                    {p.label}
                  </option>
                ))}
              </select>
            </label>

            {usesApiKey(provider) ? (
              <label className="field">
                <span className="field__label">API key</span>
                <input
                  className="input"
                  type="password"
                  autoComplete="off"
                  value={apiKey}
                  onChange={(e) => setApiKey(e.target.value)}
                  placeholder={keySet ? "•••••  key saved" : "Paste your API key"}
                  disabled={encryptionOff && !keySet}
                />
                <span className="field__hint">
                  {keySet
                    ? "A key is saved. Leave blank to keep it, or type a new one to replace it."
                    : "Stored encrypted on the server — never sent back to the browser."}
                </span>
              </label>
            ) : (
              <label className="field">
                <span className="field__label">Host</span>
                <input
                  className="input"
                  type="text"
                  value={ollamaHost}
                  onChange={(e) => setOllamaHost(e.target.value)}
                  placeholder="http://localhost:11434"
                />
                <span className="field__hint">
                  Where your local Ollama server is running.
                </span>
              </label>
            )}

            <label className="field">
              <span className="field__label">Model</span>
              <input
                className="input"
                type="text"
                value={model}
                onChange={(e) => setModel(e.target.value)}
                placeholder="Leave blank for the provider default"
              />
            </label>

            {test.kind === "ok" && (
              <p className="notice notice--ok" role="status">
                {test.detail}
              </p>
            )}
            {test.kind === "fail" && (
              <p className="notice notice--error" role="status">
                {test.detail}
              </p>
            )}
            {error && (
              <p className="notice notice--error" role="status">
                {error}
              </p>
            )}
            {saved && !error && (
              <p className="notice notice--ok" role="status">
                Settings saved.
              </p>
            )}
          </div>
        )}

        <footer className="modal__actions">
          <button
            type="button"
            className="btn btn--ghost"
            onClick={handleTest}
            disabled={loading || test.kind === "testing"}
          >
            {test.kind === "testing" ? "Testing…" : "Test connection"}
          </button>
          <button
            type="button"
            className="btn btn--primary"
            onClick={handleSave}
            disabled={loading || saving}
          >
            {saving ? "Saving…" : "Save"}
          </button>
        </footer>
      </div>
    </div>
  );
}
