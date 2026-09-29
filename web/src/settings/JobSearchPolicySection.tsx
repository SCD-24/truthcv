import { useEffect, useState } from "react";
import Alert from "@mui/material/Alert";
import TextField from "@mui/material/TextField";
import Button from "@mui/material/Button";
import FormControl from "@mui/material/FormControl";
import FormHelperText from "@mui/material/FormHelperText";
import InputLabel from "@mui/material/InputLabel";
import MenuItem from "@mui/material/MenuItem";
import Select from "@mui/material/Select";
import { getAgentConfig, updateAgentConfig } from "../api/client";
import type { AgentConfigUpdate, DorkRecency } from "../api/types";
import { SettingsSection } from "./SettingsModal";
import { SettingsAutosaveProvider, useHasSettingsAutosaveProvider, useSettingsAutosave } from "./SettingsAutosave";

/** Only these cooldown keys are owned by this panel; every PUT is partial. */
const OWNED_KEYS = [
  "cooldownDays",
  "cooldownDaysSameRole",
  "cooldownDaysSameCompany",
  "dorkRecency",
] as const satisfies readonly (keyof AgentConfigUpdate)[];
export type JobSearchPolicyKeys = Exclude<(typeof OWNED_KEYS)[number], "dorkRecency">;

const RECENCY_OPTIONS: { value: DorkRecency; label: string }[] = [
  { value: "h", label: "Past hour" },
  { value: "d", label: "Past day" },
  { value: "w", label: "Past week" },
  { value: "m", label: "Past month" },
  { value: "y", label: "Past year" },
  { value: "none", label: "Any time" },
];

function RecencyField({ value, onChange }: { value: DorkRecency; onChange: (v: DorkRecency) => void }) {
  const autosave = useSettingsAutosave("policy:dorkRecency");
  const label = "Google search recency";
  function edit(next: DorkRecency) {
    onChange(next);
    autosave.edit(next, async (v) => { await updateAgentConfig({ dorkRecency: v }); }, { valid: true });
  }
  return (
    <div>
      <FormControl size="small" sx={{ minWidth: 280 }}>
        <InputLabel id="dork-recency-label">{label}</InputLabel>
        <Select labelId="dork-recency-label" label={label} value={value}
          onChange={(e) => edit(e.target.value as DorkRecency)}>
          {RECENCY_OPTIONS.map((o) => <MenuItem key={o.value} value={o.value}>{o.label}</MenuItem>)}
        </Select>
        <FormHelperText>Narrows Google dork searches only; the posting-age hard filter is separate.</FormHelperText>
      </FormControl>
      {autosave.status === "error" && <div role="status">{label}: save failed: {autosave.error}</div>}
      {autosave.status === "error" && <Button onClick={autosave.retry}>Retry {label}</Button>}
    </div>
  );
}

function toIntOrNull(raw: string): number | null {
  if (raw.trim() === "") return null;
  const value = Number(raw);
  return Number.isSafeInteger(value) && value >= 0 ? value : NaN;
}

/** One cooldown's edits stay independent of the other windows. */
function WindowField({ label, helper, field, value, onChange }: {
  label: string;
  helper: string;
  field: JobSearchPolicyKeys;
  value: string;
  onChange: (raw: string) => void;
}) {
  const autosave = useSettingsAutosave(`policy:${field}`);

  function edit(raw: string) {
    if (raw !== "" && !/^\d*$/.test(raw)) return;
    onChange(raw);
    const parsed = toIntOrNull(raw);
    autosave.edit(parsed, async (value) => {
      await updateAgentConfig({ [field]: value });
    }, { valid: !Number.isNaN(parsed), debounce: true });
  }

  return (
    <div>
      <TextField label={label} value={value} size="small" helperText={helper}
        onChange={(e) => edit(e.target.value)} onBlur={autosave.flush}
        sx={{ maxWidth: 280 }} />
      {autosave.status !== "idle" && (
        <div role="status" aria-live="polite">
          {autosave.status === "invalid" ? `${label}: enter a whole number, 0 or more.` :
            autosave.status === "error" ? `${label}: save failed: ${autosave.error}` :
            autosave.status === "pending" ? `${label}: changes pending…` :
            autosave.status === "saving" ? `${label}: saving…` : `${label}: saved.`}
        </div>
      )}
      {autosave.status === "error" && <Button onClick={autosave.retry}>Retry {label}</Button>}
    </div>
  );
}

/** Blank inherits the fallback; 0 disables a window. Loading never writes. */
export function JobSearchPolicySection() {
  const hasProvider = useHasSettingsAutosaveProvider();
  return hasProvider ? <JobSearchPolicyContent /> :
    <SettingsAutosaveProvider><JobSearchPolicyContent /></SettingsAutosaveProvider>;
}

function JobSearchPolicyContent() {
  const [values, setValues] = useState<Record<JobSearchPolicyKeys, string>>({
    cooldownDays: "", cooldownDaysSameRole: "", cooldownDaysSameCompany: "",
  });
  const [recency, setRecency] = useState<DorkRecency>("d");
  const [loaded, setLoaded] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let alive = true;
    getAgentConfig()
      .then((cfg) => {
        if (!alive) return;
        setValues({
          cooldownDays: cfg.cooldownDays?.toString() ?? "",
          cooldownDaysSameRole: cfg.cooldownDaysSameRole?.toString() ?? "",
          cooldownDaysSameCompany: cfg.cooldownDaysSameCompany?.toString() ?? "",
        });
        setRecency(cfg.dorkRecency ?? "d");
        setLoaded(true);
      })
      .catch((e: unknown) => {
        if (alive) setError(e instanceof Error ? e.message : "Couldn't load agent config.");
      });
    return () => { alive = false; };
  }, []);

  const fields: { key: JobSearchPolicyKeys; label: string; helper: string }[] = [
    { key: "cooldownDaysSameRole", label: "Same role cooldown (days)", helper: "Blank inherits Cooldown days; 0 disables" },
    { key: "cooldownDaysSameCompany", label: "Same company cooldown (days)", helper: "Blank inherits Cooldown days; 0 disables" },
    { key: "cooldownDays", label: "Cooldown days (fallback)", helper: "Used when a window is blank; blank falls back to 90" },
  ];

  return (
    <div id="job-search-policy-section">
      <SettingsSection title="Job search policy"
        description="How long TruthCV waits before re-contacting the same company or role.">
        {error && <Alert severity="error">{error}</Alert>}
        {!loaded && !error && <span>Loading job search policy…</span>}
        {loaded && <RecencyField value={recency} onChange={setRecency} />}
        {loaded && fields.map(({ key, label, helper }) => (
          <WindowField key={key} field={key} label={label} helper={helper} value={values[key]}
            onChange={(raw) => setValues((previous) => ({ ...previous, [key]: raw }))} />
        ))}
      </SettingsSection>
    </div>
  );
}
