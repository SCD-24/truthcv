import { useEffect, useRef, useState } from "react";
import Stack from "@mui/material/Stack";
import Button from "@mui/material/Button";
import Alert from "@mui/material/Alert";
import TextField from "@mui/material/TextField";
import MenuItem from "@mui/material/MenuItem";
import { listConnectionModels, testConnectionProvider } from "../api/client";
import { ButtonSpinner } from "../components/ButtonSpinner";
import { SettingsSection } from "./SettingsModal";
import { ModelSelect } from "./ModelSelect";
import { useSettingsAutosave } from "./SettingsAutosave";
import type { ConnectionStatus, ModelInfo, RouteChoice } from "../api/types";

type PickerDraft = {
  connection: string;
  model: string;
  custom: boolean;
  effort: string;
  context: string;
  needsCommit: boolean;
};

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
  autosaveKey,
  allowDefaultCommit = false,
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
  /** Opt-in only: Agents' shared picker keeps its manual Save button. */
  autosaveKey?: string;
  /** Expose a deliberate commit for the modal's initial provider fallback. */
  allowDefaultCommit?: boolean;
}) {
  const connectedConnections = connections
    .filter(isConnected)
    .filter((c) => !filterCards || filterCards.includes(c.provider));
  const connectedKey = connectedConnections.map((c) => c.provider).join(" ");

  const autosave = useSettingsAutosave(autosaveKey ?? `manual:${title}`);
  const [restored] = useState(() => autosaveKey ? autosave.draft<PickerDraft>() : undefined);
  const [connection, setConnection] = useState(
    restored?.connection ?? route?.connection ?? connectedConnections[0]?.provider ?? "",
  );
  const [model, setModel] = useState(restored?.model ?? route?.model ?? "");
  const [customModel, setCustomModel] = useState(restored?.custom ?? false);
  const [models, setModels] = useState<ModelInfo[]>([]);
  const [modelsLoading, setModelsLoading] = useState(false);
  const [modelsError, setModelsError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);
  const [saved, setSaved] = useState(false);
  const [needsCommit, setNeedsCommit] = useState(
    restored?.needsCommit ?? (route === null || !connectedConnections.some((c) => c.provider === route.connection)),
  );
  const [error, setError] = useState<string | null>(null);
  const [test, setTest] = useState<TestState>({ kind: "idle" });
  const [effort, setEffort] = useState(restored?.effort ?? route?.effort ?? "");
  const [contextWindow, setContextWindow] = useState(restored?.context ?? String(route?.contextWindow ?? 0));
  const requestId = useRef(0);
  const draftModel = useRef(restored?.model ?? route?.model ?? "");

  function queueChoice(next: { connection: string; model: string; custom: boolean; effort: string; context: string }, debounce = false) {
    if (!autosaveKey || autosave.locked) return;
    const window = Number(next.context);
    const validWindow = next.context.trim() !== "" && Number.isSafeInteger(window) && (window === 0 || window >= 8192);
    const choice: RouteChoice = { connection: next.connection, model: next.model };
    if (next.effort) choice.effort = next.effort;
    if (window > 0) choice.contextWindow = window;
    const valid = !!next.connection && (!next.custom || !!next.model.trim()) && validWindow;
    if (valid) setNeedsCommit(false);
    autosave.edit(choice, onSave, { valid, debounce,
      draft: { ...next, needsCommit: !valid },
    });
  }

  /** Effort levels advertised by the currently selected listed model.
   * Empty when the model is a custom id, blank, or has no effort support. */
  const activeEffortLevels: string[] =
    !customModel && model
      ? (models.find((m) => m.id === model)?.effortLevels ?? [])
      : [];

  // Pull the connection's model list live. Returns the list so callers can
  // decide whether the current model is a known option or a custom id.
  async function loadModels(conn: string): Promise<ModelInfo[]> {
    const id = ++requestId.current;
    if (!conn) {
      setModels([]);
      return [];
    }
    setModelsLoading(true);
    setModelsError(null);
    try {
      const list = (await listConnectionModels(conn)) ?? [];
      if (id === requestId.current) setModels(list);
      return list;
    } catch (e) {
      if (id === requestId.current) {
        setModels([]);
        setModelsError(e instanceof Error ? e.message : "Couldn't load models.");
      }
      return [];
    } finally {
      if (id === requestId.current) setModelsLoading(false);
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
    draftModel.current = "";
    setCustomModel(false);
    setEffort("");
    setModels([]);
    setTest({ kind: "idle" });
    setNeedsCommit(true);
    if (autosaveKey) autosave.cancel();
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
    const initialModel = draftModel.current;
    const id = requestId.current + 1;
    loadModels(connection).then((list) => {
      if (alive && id === requestId.current && initialModel && draftModel.current === initialModel && !restored?.custom) {
        setCustomModel(!list.some((m) => m.id === initialModel));
      }
    });
    return () => {
      alive = false;
      requestId.current++;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [connection, connectedKey]);

  async function handleSave() {
    setSaving(true);
    setError(null);
    setSaved(false);
    try {
      const routeChoice: RouteChoice = { connection, model };
      if (effort) routeChoice.effort = effort;
      if (Number(contextWindow) > 0) routeChoice.contextWindow = Number(contextWindow);
      await onSave(routeChoice);
      setSaved(true);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Couldn't save routing.");
    } finally {
      setSaving(false);
    }
  }

  async function handleClear() {
    if (autosaveKey) {
      if (autosave.locked) return;
      setModel("");
      draftModel.current = "";
      setCustomModel(false);
      setEffort("");
      setNeedsCommit(true);
      autosave.edit(null, onSave, { draft: { connection, model: "", custom: false,
        effort: "", context: contextWindow, needsCommit: true } satisfies PickerDraft });
      return;
    }
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
      <fieldset disabled={!!autosaveKey && autosave.locked}
        style={{ border: 0, padding: 0, margin: 0, minWidth: 0,
          opacity: autosaveKey && autosave.locked ? 0.5 : 1,
          pointerEvents: autosaveKey && autosave.locked ? "none" : "auto" }}>
      <TextField
        select
        label="Connection"
        value={connection}
        onChange={(e) => {
          if (autosaveKey && autosave.locked) return;
          const next = e.target.value;
          setConnection(next);
          setModel("");
          draftModel.current = "";
          setCustomModel(false);
          setEffort("");
          setTest({ kind: "idle" });
          queueChoice({ connection: next, model: "", custom: false, effort: "", context: contextWindow });
        }}
      >
        {connectedConnections.map((c) => (
          <MenuItem key={c.provider} value={c.provider}>
            {c.label}
          </MenuItem>
        ))}
      </TextField>

      <div onBlur={() => autosaveKey && autosave.flush()}>
      <ModelSelect
        models={models}
        model={model}
        customModel={customModel}
        onChange={({ model: v, customModel: isCustom }) => {
          if (autosaveKey && autosave.locked) return;
          draftModel.current = v;
          if (isCustom && !customModel) {
            // Picking "Custom…" from the list.
            setCustomModel(true);
            setModel("");
            setEffort("");
            queueChoice({ connection, model: "", custom: true, effort: "", context: contextWindow });
          } else if (isCustom) {
            // Typing in the free-text field.
            setModel(v);
            queueChoice({ connection, model: v, custom: true, effort: "", context: contextWindow }, true);
          } else {
            setCustomModel(false);
            setModel(v);
            // Reset effort when switching to a model whose capability set differs.
            const newLevels = models.find((m) => m.id === v)?.effortLevels ?? [];
            if (effort && !newLevels.includes(effort)) setEffort("");
            queueChoice({ connection, model: v, custom: false, effort: newLevels.includes(effort) ? effort : "", context: contextWindow });
          }
        }}
        onReload={() => { if (!autosave.locked) void loadModels(connection); }}
        modelsLoading={modelsLoading}
        modelsError={modelsError}
        connection={connection}
      />
      </div>

      {activeEffortLevels.length > 0 && (
        <TextField
          select
          fullWidth
          label="Effort level"
          value={effort}
          onChange={(e) => {
            if (autosaveKey && autosave.locked) return;
            setEffort(e.target.value);
            queueChoice({ connection, model, custom: customModel, effort: e.target.value, context: contextWindow });
          }}
          helperText="Controls the model's reasoning depth. Provider default leaves it unset."
        >
          <MenuItem value="">Provider default</MenuItem>
          {activeEffortLevels.map((level) => (
            <MenuItem key={level} value={level}>
              {level.charAt(0).toUpperCase() + level.slice(1)}
            </MenuItem>
          ))}
        </TextField>
      )}

      <TextField
        fullWidth
        type="number"
        label="Context window (tokens)"
        value={contextWindow}
        onChange={(e) => {
          if (autosaveKey && autosave.locked) return;
          setContextWindow(e.target.value);
          queueChoice({ connection, model, custom: customModel, effort, context: e.target.value }, true);
        }}
        onBlur={() => autosaveKey && autosave.flush()}
        helperText="Model input capacity; 0 = unknown, minimum 8192"
      />
      </fieldset>

      {test.kind === "ok" && <Alert severity="success">{test.detail}</Alert>}
      {test.kind === "fail" && <Alert severity="error">{test.detail}</Alert>}
      {autosaveKey && autosave.status !== "idle" && !(needsCommit && autosave.status === "saved") && (
        <div role="status" aria-live="polite">
          {autosave.status === "invalid" ? "Complete a valid model and context window before closing." :
            autosave.status === "error" ? `Save failed: ${autosave.error}` :
            autosave.status === "pending" ? "Changes pending…" :
            autosave.status === "saving" ? "Saving…" : savedLabel}
        </div>
      )}
      {autosaveKey && autosave.status === "error" && <Button disabled={autosave.locked} onClick={autosave.retry}>Retry save</Button>}
      {!autosaveKey && error && <Alert severity="error">{error}</Alert>}
      {!autosaveKey && saved && !error && <Alert severity="success">{savedLabel}</Alert>}

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
          <Button variant="outlined" onClick={handleClear} disabled={(!!autosaveKey && autosave.locked) || (!autosaveKey && saving)}>
            Clear
          </Button>
        )}
        {autosaveKey && allowDefaultCommit && needsCommit && (
          <Button variant="outlined" disabled={autosave.locked || !connection || (customModel && !model.trim()) || !contextWindow.trim() ||
            !Number.isSafeInteger(Number(contextWindow)) ||
            !(Number(contextWindow) === 0 || Number(contextWindow) >= 8192)}
            onClick={() => queueChoice({ connection, model, custom: customModel, effort, context: contextWindow })}>
            Use this provider default
          </Button>
        )}
        {!autosaveKey && (
          <Button variant="contained" onClick={handleSave} disabled={!connection || saving}>
            {saving ? "Saving…" : saveLabel}
          </Button>
        )}
      </Stack>
    </SettingsSection>
  );
}
