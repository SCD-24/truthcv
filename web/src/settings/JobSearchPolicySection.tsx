import { useEffect, useState } from "react";
import Alert from "@mui/material/Alert";
import TextField from "@mui/material/TextField";
import Button from "@mui/material/Button";
import { getAgentConfig, updateAgentConfig } from "../api/client";
import type { AgentConfigUpdate } from "../api/types";
import { SettingsSection } from "./SettingsModal";

/** The cooldown windows and CV conventions this section owns. Exactly one
 * writer per field: saving PUTs only these keys so profiles, schedule,
 * blocklist and everything else on the config are never clobbered. */
const OWNED_KEYS = [
  "cooldownDays",
  "cooldownDaysSameRole",
  "cooldownDaysSameCompany",
] as const satisfies readonly (keyof AgentConfigUpdate)[];

function toIntOrNull(raw: string): number | null {
  const trimmed = raw.trim();
  if (trimmed === "") return null;
  const n = Number(trimmed);
  return Number.isInteger(n) && n >= 0 ? n : NaN;
}

/** One numeric settings row: blank means "not set" (inherit the fallback). */
function WindowField({
  label,
  helper,
  value,
  onChange,
}: {
  label: string;
  helper?: string;
  value: string;
  onChange: (v: string) => void;
}) {
  return (
    <TextField
      label={label}
      value={value}
      size="small"
      helperText={helper}
      onChange={(e) => {
        const raw = e.target.value;
        if (raw !== "" && !/^\d*$/.test(raw)) return; // digits only
        onChange(raw);
      }}
      sx={{ maxWidth: 280 }}
    />
  );
}

/** Job search policy: the two cooldown windows. Blank inherits the legacy
 * single window, then the default of 90; 0 disables a window. */
export function JobSearchPolicySection() {
  const [sameRole, setSameRole] = useState("");
  const [sameCompany, setSameCompany] = useState("");
  const [legacyDays, setLegacyDays] = useState("");
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [saved, setSaved] = useState(false);

  useEffect(() => {
    let alive = true;
    getAgentConfig()
      .then((cfg) => {
        if (!alive) return;
        setSameRole(cfg.cooldownDaysSameRole?.toString() ?? "");
        setSameCompany(cfg.cooldownDaysSameCompany?.toString() ?? "");
        setLegacyDays(cfg.cooldownDays?.toString() ?? "");
      })
      .catch((e: unknown) =>
        setError(e instanceof Error ? e.message : "Couldn't load agent config."),
      );
    return () => {
      alive = false;
    };
  }, []);

  async function save() {
    const role = toIntOrNull(sameRole);
    const company = toIntOrNull(sameCompany);
    const legacy = toIntOrNull(legacyDays);
    if (Number.isNaN(role) || Number.isNaN(company) || Number.isNaN(legacy)) {
      setError("Cooldown days must be a whole number, 0 or more.");
      return;
    }
    setSaving(true);
    setError(null);
    try {
      await updateAgentConfig({
        cooldownDaysSameRole: role,
        cooldownDaysSameCompany: company,
        cooldownDays: legacy,
      });
      setSameRole(role === null ? "" : String(role));
      setSameCompany(company === null ? "" : String(company));
      setLegacyDays(legacy === null ? "" : String(legacy));
      setSaved(true);
      setTimeout(() => setSaved(false), 2500);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Couldn't save job search policy.");
    } finally {
      setSaving(false);
    }
  }

  return (
    <div id="job-search-policy-section">
    <SettingsSection
      title="Job search policy"
      description="How long TruthCV waits before re-contacting the same company or role."
    >
      {error && <Alert severity="error">{error}</Alert>}
      {saved && <Alert severity="success">Job search policy saved.</Alert>}
      <WindowField
        label="Same role cooldown (days)"
        helper="Blank inherits Cooldown days; 0 disables"
        value={sameRole}
        onChange={setSameRole}
      />
      <WindowField
        label="Same company cooldown (days)"
        helper="Blank inherits Cooldown days; 0 disables"
        value={sameCompany}
        onChange={setSameCompany}
      />
      <WindowField
        label="Cooldown days (fallback)"
        helper="Used when a window is blank; blank falls back to 90"
        value={legacyDays}
        onChange={setLegacyDays}
      />
      <div>
        <Button variant="contained" onClick={save} disabled={saving}>
          Save job search policy
        </Button>
      </div>
    </SettingsSection>
    </div>
  );
}

// Keep the owned-keys list honest with what save() actually sends.
export type JobSearchPolicyKeys = (typeof OWNED_KEYS)[number];
