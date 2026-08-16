import { useEffect, useState } from "react";
import type { ReactNode } from "react";
import Dialog from "@mui/material/Dialog";
import DialogTitle from "@mui/material/DialogTitle";
import DialogContent from "@mui/material/DialogContent";
import DialogActions from "@mui/material/DialogActions";
import Box from "@mui/material/Box";
import Stack from "@mui/material/Stack";
import Button from "@mui/material/Button";
import IconButton from "@mui/material/IconButton";
import CloseIcon from "@mui/icons-material/Close";
import DeleteOutlineIcon from "@mui/icons-material/DeleteOutlined";
import Divider from "@mui/material/Divider";
import Alert from "@mui/material/Alert";
import TextField from "@mui/material/TextField";
import MenuItem from "@mui/material/MenuItem";
import InputAdornment from "@mui/material/InputAdornment";
import Typography from "@mui/material/Typography";
import Table from "@mui/material/Table";
import TableBody from "@mui/material/TableBody";
import TableCell from "@mui/material/TableCell";
import TableHead from "@mui/material/TableHead";
import TableRow from "@mui/material/TableRow";
import Chip from "@mui/material/Chip";
import Tooltip from "@mui/material/Tooltip";
import {
  deleteScreening,
  getProfileAnswers,
  getSettings,
  listModels,
  listScreenings,
  saveProfileAnswers,
  saveSettings,
  testConnection,
} from "../api/client";
import { ButtonSpinner } from "../components/ButtonSpinner";
import { isCooldownActive } from "./cooldown";
import { lastAgentActivity } from "./agentActivity";
import type {
  ModelInfo,
  ProfileAnswers,
  ProviderName,
  ScreeningRecord,
  SettingsStatus,
  SettingsUpdate,
} from "../api/types";
import "../styles/settings.css";

/** A titled group of settings fields, separated from its siblings by a
 * Divider in the caller. Establishes the one section pattern the modal's
 * panels share. */
function SettingsSection({
  title,
  description,
  children,
}: {
  title: string;
  description?: string;
  children: ReactNode;
}) {
  return (
    <Stack spacing={2}>
      <Stack spacing={0.5}>
        <Typography variant="h6">{title}</Typography>
        {description && (
          <Typography variant="body2" color="text.secondary">
            {description}
          </Typography>
        )}
      </Stack>
      <Stack spacing={2}>{children}</Stack>
    </Stack>
  );
}

/** How a cooldown reads in the table: the active/expired/none label the chip
 * carries, kept separate from the pure isCooldownActive predicate. */
function cooldownLabel(record: ScreeningRecord, active: boolean): string {
  if (active) return `Until ${record.cooldownExpires}`;
  return record.cooldownExpires ? "Expired" : "No cooldown";
}

/** One rejected-target row: company/reason, role, verdict, why it failed, its
 * cooldown state, and a delete control to un-block it. Kept as its own
 * component so the table body stays a one-line map in the panel above. */
function ScreeningRow({
  record,
  deleting,
  onDelete,
}: {
  record: ScreeningRecord;
  deleting: boolean;
  onDelete: (id: string) => void;
}) {
  const active = isCooldownActive(record.cooldownExpires);
  return (
    <TableRow>
      <TableCell>
        <Tooltip title={record.reason || "No reason recorded."}>
          <Typography variant="body2">{record.company || "—"}</Typography>
        </Tooltip>
      </TableCell>
      <TableCell>{record.role || "—"}</TableCell>
      <TableCell>{record.verdict || "—"}</TableCell>
      <TableCell>{record.failingCriterion || "—"}</TableCell>
      <TableCell>
        <Chip
          size="small"
          variant="outlined"
          color={active ? "warning" : "default"}
          label={cooldownLabel(record, active)}
        />
      </TableCell>
      <TableCell align="right">
        <IconButton
          aria-label={`Delete screening record for ${record.company || "this target"}`}
          onClick={() => onDelete(record.id)}
          disabled={deleting}
          size="small"
        >
          <DeleteOutlineIcon fontSize="small" />
        </IconButton>
      </TableCell>
    </TableRow>
  );
}

/** The times the unattended application agent runs each day. This MIRRORS the
 * `RUN_AT` environment variable set on the agent service in
 * docker-compose.yml (e.g. `RUN_AT=09:00,15:00`) — there is no agent status
 * endpoint to read this from, so it is a hardcoded display-only copy. If the
 * agent's `RUN_AT` schedule is ever changed there, this constant MUST be
 * updated to match, or the times shown here will be quietly wrong. */
const AGENT_RUN_TIMES = ["09:00", "15:00"] as const;

/** Read-only summary of the unattended agent's schedule and its last
 * recorded activity, so the user can tell it's alive without reading
 * container logs. The run times are a fixed mirror of the agent's `RUN_AT`
 * config (see AGENT_RUN_TIMES); "last activity" is the newest screening
 * record's date, an honest proxy since the agent is the only writer of
 * screening records — not a real run log, which TruthCV doesn't have. */
function AgentSchedule({ screenings }: { screenings: ScreeningRecord[] }) {
  const last = lastAgentActivity(screenings);
  const lastLabel = last ? new Date(last).toLocaleDateString() : null;
  return (
    <Stack spacing={1.5}>
      <Stack direction="row" spacing={1}>
        {AGENT_RUN_TIMES.map((time) => (
          <Chip key={time} variant="outlined" size="small" label={time} />
        ))}
      </Stack>
      {lastLabel ? (
        <Typography variant="body2" color="text.secondary">
          Last recorded activity: {lastLabel} — the date of its most recent
          screening record, the closest thing to a run log TruthCV has.
        </Typography>
      ) : (
        <Typography variant="body2" color="text.secondary">
          The agent hasn't recorded any activity yet.
        </Typography>
      )}
    </Stack>
  );
}

/** The five canonical ATS answers before they're loaded from the server. */
const EMPTY_ANSWERS: ProfileAnswers = {
  phone: "",
  workAuthorisation: "",
  salaryExpectation: "",
  noticePeriod: "",
  locationPreference: "",
  canonicalCvAssetId: null,
};

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
  const [answers, setAnswers] = useState<ProfileAnswers>(EMPTY_ANSWERS);
  const [screenings, setScreenings] = useState<ScreeningRecord[]>([]);
  const [deletingScreeningId, setDeletingScreeningId] = useState<string | null>(null);
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

  // Load current status, the profile answers, and the screening/cooldown
  // ledger once when the modal opens.
  useEffect(() => {
    let alive = true;
    Promise.all([getSettings(), getProfileAnswers(), listScreenings()])
      .then(([s, a, sc]) => {
        if (!alive) return;
        const prov = s.activeProvider || "anthropic";
        setStatus(s);
        setProvider(prov);
        setModel(s.model || "");
        setOllamaHost(s.ollamaHost || "");
        setAnswers(a);
        setScreenings(sc);
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
      const freshAnswers = await saveProfileAnswers({
        phone: answers.phone,
        workAuthorisation: answers.workAuthorisation,
        salaryExpectation: answers.salaryExpectation,
        noticePeriod: answers.noticePeriod,
        locationPreference: answers.locationPreference,
      });
      setAnswers(freshAnswers);
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

  // Delete one screening record and drop it from local state directly —
  // no refetch of the list, no reload of the modal.
  async function handleDeleteScreening(id: string) {
    setDeletingScreeningId(id);
    setError(null);
    try {
      await deleteScreening(id);
      setScreenings((prev) => prev.filter((r) => r.id !== id));
    } catch (e) {
      setError(
        e instanceof Error ? e.message : "Couldn't delete the screening record.",
      );
    } finally {
      setDeletingScreeningId(null);
    }
  }

  const encryptionOff = status ? !status.encryptionAvailable : false;
  const keySet = keyIsSet(status, provider);

  return (
    <Dialog open onClose={onClose} maxWidth="md" fullWidth aria-labelledby="settings-title">
      <DialogTitle
        id="settings-title"
        sx={{ display: "flex", alignItems: "center", justifyContent: "space-between" }}
      >
        Settings
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
          <Stack spacing={3}>
            <SettingsSection title="Provider">
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
                          {modelsLoading && <ButtonSpinner size={12} />}
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
            </SettingsSection>

            <Divider />

            <SettingsSection
              title="Profile answers"
              description="The canonical answers the unattended application agent types into ATS forms when it submits on your behalf. Keep them accurate — they go out with every application."
            >
              <TextField
                fullWidth
                label="Phone"
                value={answers.phone}
                onChange={(e) => setAnswers({ ...answers, phone: e.target.value })}
                helperText="What the agent types into ATS phone fields."
              />
              <TextField
                fullWidth
                label="Work authorisation"
                value={answers.workAuthorisation}
                onChange={(e) =>
                  setAnswers({ ...answers, workAuthorisation: e.target.value })
                }
                helperText='What the agent types into ATS work-authorisation questions — e.g. "Authorised to work in the UK, no sponsorship required."'
              />
              <TextField
                fullWidth
                label="Salary expectation"
                value={answers.salaryExpectation}
                onChange={(e) =>
                  setAnswers({ ...answers, salaryExpectation: e.target.value })
                }
                helperText="What the agent types into ATS salary-expectation fields."
              />
              <TextField
                fullWidth
                label="Notice period"
                value={answers.noticePeriod}
                onChange={(e) =>
                  setAnswers({ ...answers, noticePeriod: e.target.value })
                }
                helperText="What the agent types into ATS notice-period fields."
              />
              <TextField
                fullWidth
                label="Location preference"
                value={answers.locationPreference}
                onChange={(e) =>
                  setAnswers({ ...answers, locationPreference: e.target.value })
                }
                helperText="What the agent types into ATS location/relocation fields."
              />
            </SettingsSection>

            <Divider />

            <SettingsSection
              title="Screening & cooldowns"
              description="Targets the unattended application agent rejected, why, and how long each stays in cooldown before it's reconsidered. Delete a record to un-block a target immediately."
            >
              {screenings.length === 0 ? (
                <Typography variant="body2" color="text.secondary">
                  The agent hasn't rejected any targets yet.
                </Typography>
              ) : (
                <Table size="small">
                  <TableHead>
                    <TableRow>
                      <TableCell>Company</TableCell>
                      <TableCell>Role</TableCell>
                      <TableCell>Verdict</TableCell>
                      <TableCell>Failing criterion</TableCell>
                      <TableCell>Cooldown</TableCell>
                      <TableCell align="right">Delete</TableCell>
                    </TableRow>
                  </TableHead>
                  <TableBody>
                    {screenings.map((record) => (
                      <ScreeningRow
                        key={record.id}
                        record={record}
                        deleting={deletingScreeningId === record.id}
                        onDelete={handleDeleteScreening}
                      />
                    ))}
                  </TableBody>
                </Table>
              )}
            </SettingsSection>

            <Divider />

            <SettingsSection
              title="Agent schedule"
              description="The unattended application agent runs at these times each day. The schedule is configured on the agent's container — it's read-only here."
            >
              <AgentSchedule screenings={screenings} />
            </SettingsSection>

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
          {test.kind === "testing" && <ButtonSpinner />}
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
