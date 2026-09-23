import { useEffect, useState } from "react";
import Alert from "@mui/material/Alert";
import TextField from "@mui/material/TextField";
import Button from "@mui/material/Button";
import { getAgentConfig, updateAgentConfig } from "../api/client";
import type { AgentConfigUpdate } from "../api/types";
import { SettingsSection } from "./SettingsModal";
import { SettingsAutosaveProvider, useHasSettingsAutosaveProvider, useSettingsAutosave } from "./SettingsAutosave";

/** Only these cooldown keys are owned by this panel; every PUT is partial. */
const OWNED_KEYS = [
  "cooldownDays",
  "cooldownDaysSameRole",
  "cooldownDaysSameCompany",
] as const satisfies readonly (keyof AgentConfigUpdate)[];
export type JobSearchPolicyKeys = (typeof OWNED_KEYS)[number];

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
        {loaded && fields.map(({ key, label, helper }) => (
          <WindowField key={key} field={key} label={label} helper={helper} value={values[key]}
            onChange={(raw) => setValues((previous) => ({ ...previous, [key]: raw }))} />
        ))}
      </SettingsSection>
    </div>
  );
}
