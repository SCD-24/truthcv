import { useEffect, useState } from "react";
import Box from "@mui/material/Box";
import Stack from "@mui/material/Stack";
import Paper from "@mui/material/Paper";
import Card from "@mui/material/Card";
import CardContent from "@mui/material/CardContent";
import Button from "@mui/material/Button";
import ArrowBackIcon from "@mui/icons-material/ArrowBack";
import Alert from "@mui/material/Alert";
import Switch from "@mui/material/Switch";
import FormControlLabel from "@mui/material/FormControlLabel";
import Checkbox from "@mui/material/Checkbox";
import TextField from "@mui/material/TextField";
import MenuItem from "@mui/material/MenuItem";
import Typography from "@mui/material/Typography";
import CircularProgress from "@mui/material/CircularProgress";
import Chip from "@mui/material/Chip";
import {
  getAgentConfig,
  getProfileAnswers,
  getRouting,
  listConnections,
  saveProfileAnswers,
  updateAgentConfig,
  updateRouting,
} from "../api/client";
import { ButtonSpinner } from "../components/ButtonSpinner";
import { ModelRoutePicker } from "../settings/ModelRoutePicker";
import { isValidRunTime, WEEKDAYS } from "./schedule";
import type {
  AgentConfig,
  ConnectionStatus,
  JobProfile,
  ProfileAnswers,
  Routing,
} from "../api/types";

/** The 20 text answers to ATS screening questions and cover-letter claim sources.
 * Salary is deliberately absent: it comes from the matched job profile's
 * band via recommend_salary. canonicalCvAssetId is read-only, never sent in saves. */
const EMPTY_ANSWERS: ProfileAnswers = {
  phone: "",
  workAuthorisation: "",
  noticePeriod: "",
  locationPreference: "",
  canonicalCvAssetId: null,
  name: "",
  email: "",
  linkedin: "",
  github: "",
  website: "",
  requiresSponsorship: "",
  authorizedNonGermanCountry: "",
  languages: "",
  highestRelevantDegree: "",
  otherDegree: "",
  csDegree: "",
  gpa: "",
  gender: "",
  yearsOfExperience: "",
  currentRole: "",
  howDidYouHear: "",
};

/** A titled Paper block — the one section pattern the page's panels share. */
function Section({
  title,
  description,
  children,
}: {
  title: string;
  description?: string;
  children: React.ReactNode;
}) {
  return (
    <Paper variant="outlined" sx={{ p: 3 }}>
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
    </Paper>
  );
}

/**
 * The Agents page — enable/disable the unattended application agent, edit its
 * run schedule and blocklist, and edit the ATS profile answers it submits.
 * Reached from the rail (wired in a later task); `onBack` returns to the
 * wizard step left behind.
 *
 * Each section owns its own error/success state and saves independently, so a
 * failure in one (e.g. a bad schedule save) never blocks or clobbers another.
 */
export function AgentsPage({ onBack }: { onBack: () => void }) {
  const [config, setConfig] = useState<AgentConfig | null>(null);
  const [answers, setAnswers] = useState<ProfileAnswers>(EMPTY_ANSWERS);
  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState<string | null>(null);

  const [connections, setConnections] = useState<ConnectionStatus[]>([]);
  const [routing, setRouting] = useState<Routing | null>(null);
  const [modelLoadError, setModelLoadError] = useState<string | null>(null);

  useEffect(() => {
    let alive = true;
    Promise.all([getAgentConfig(), getProfileAnswers()])
      .then(([c, a]) => {
        if (!alive) return;
        setConfig(c);
        setAnswers(a);
      })
      .catch((e: unknown) =>
        setLoadError(e instanceof Error ? e.message : "Couldn't load the agent's configuration."),
      )
      .finally(() => alive && setLoading(false));
    return () => {
      alive = false;
    };
  }, []);

  // Loaded on its own chain, separate from the three loads above: a routing
  // or connections failure must only take out the Model section, per this
  // file's own per-section failure-isolation contract — not the whole page.
  useEffect(() => {
    let alive = true;
    Promise.all([getRouting(), listConnections()])
      .then(([r, conns]) => {
        if (!alive) return;
        setRouting(r);
        setConnections(conns.connections);
      })
      .catch((e: unknown) => {
        if (!alive) return;
        setModelLoadError(e instanceof Error ? e.message : "Couldn't load the model section.");
      });
    return () => {
      alive = false;
    };
  }, []);

  return (
    <Box aria-labelledby="agents-title">
      <Stack
        direction="row"
        sx={{ mb: 3, alignItems: "flex-start", justifyContent: "space-between", gap: 2 }}
      >
        <Typography id="agents-title" variant="h4" component="h1">
          Agents
        </Typography>
        <Button variant="text" startIcon={<ArrowBackIcon fontSize="small" />} onClick={onBack}>
          Back to wizard
        </Button>
      </Stack>

      {loadError && (
        <Alert severity="error" sx={{ mb: 2 }}>
          {loadError}
        </Alert>
      )}

      {loading ? (
        <Stack direction="row" spacing={2} sx={{ py: 6, justifyContent: "center" }}>
          <CircularProgress size={20} sx={{ color: "var(--attest)" }} />
          <Typography color="text.secondary">Loading agent configuration…</Typography>
        </Stack>
      ) : config ? (
        <Stack spacing={3}>
          <EnabledSection
            config={config}
            onChange={(updater) => setConfig((cur) => (cur ? updater(cur) : cur))}
          />
          {routing ? (
            <ModelSection connections={connections} routing={routing} onSaved={setRouting} />
          ) : (
            modelLoadError && (
              <Section title="Model">
                <Alert severity="error">{modelLoadError}</Alert>
              </Section>
            )
          )}
          <ScheduleSection config={config} onChange={setConfig} />
          <ProfilesSection config={config} onChange={setConfig} />
          <BlocklistSection config={config} onChange={setConfig} />
          <ProfileAnswersSection answers={answers} onChange={setAnswers} />
        </Stack>
      ) : null}
    </Box>
  );
}

/** Agent enabled/disabled toggle. Optimistic — flips immediately, reverts and
 * surfaces an error if the PUT fails.
 *
 * `onChange` takes an updater over the *current* config rather than a
 * snapshot, so the optimistic set and its revert only ever touch the
 * `enabled` field against whatever the latest state is — a save from
 * another section (e.g. Schedule) that lands while this PUT is in flight
 * is never clobbered by a stale full-config revert. */
function EnabledSection({
  config,
  onChange,
}: {
  config: AgentConfig;
  onChange: (updater: (prev: AgentConfig) => AgentConfig) => void;
}) {
  const [error, setError] = useState<string | null>(null);

  async function handleToggle(enabled: boolean) {
    setError(null);
    onChange((prev) => ({ ...prev, enabled }));
    try {
      const fresh = await updateAgentConfig({ enabled });
      onChange((prev) => ({ ...prev, enabled: fresh.enabled }));
    } catch (e) {
      onChange((prev) => ({ ...prev, enabled: !enabled }));
      setError(e instanceof Error ? e.message : "Couldn't update the agent.");
    }
  }

  return (
    <Section title="Agent">
      <FormControlLabel
        control={
          <Switch checked={config.enabled} onChange={(e) => handleToggle(e.target.checked)} />
        }
        label="Agent enabled"
      />
      <Typography variant="body2" color="text.secondary">
        When off, scheduled runs wake, log that the agent is disabled, and
        exit. Nothing is submitted until re-enabled.
      </Typography>
      {error && <Alert severity="error">{error}</Alert>}
    </Section>
  );
}

/** The model the unattended agent runs on — a claude-only ModelRoutePicker
 * (the agent drives the operator's own Chrome via the interceptor, which
 * only supports Claude) saving/clearing the `agent` route. Cleared falls
 * back to the container's ANTHROPIC_API_KEY. */
function ModelSection({
  connections,
  routing,
  onSaved,
}: {
  connections: ConnectionStatus[];
  routing: Routing;
  onSaved: (r: Routing) => void;
}) {
  return (
    <ModelRoutePicker
      connections={connections}
      route={routing.agent}
      onSave={async (route) => {
        const fresh = await updateRouting({ agent: route });
        onSaved(fresh);
      }}
      title="Model"
      description="Model and account the unattended agent runs on. Cleared = the container's ANTHROPIC_API_KEY."
      filterCards={["claude"]}
      allowClear
      showTest={false}
    />
  );
}

/** Run-time chips + weekday checkboxes. Guards: at least one run time and one
 * weekday must remain; Add is gated on isValidRunTime with an inline error. */
function ScheduleSection({
  config,
  onChange,
}: {
  config: AgentConfig;
  onChange: (c: AgentConfig) => void;
}) {
  const [runAt, setRunAt] = useState<string[]>(config.runAt);
  const [runDays, setRunDays] = useState<string[]>(config.runDays);
  const [newTime, setNewTime] = useState("");
  const [timeError, setTimeError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [saved, setSaved] = useState(false);

  function handleAddTime() {
    if (!isValidRunTime(newTime)) {
      setTimeError("Enter a 24-hour time as HH:MM, e.g. 09:00.");
      return;
    }
    if (runAt.includes(newTime)) {
      setTimeError("That run time is already in the schedule.");
      return;
    }
    setTimeError(null);
    setRunAt([...runAt, newTime]);
    setNewTime("");
  }

  function handleRemoveTime(time: string) {
    if (runAt.length <= 1) return;
    setRunAt(runAt.filter((t) => t !== time));
  }

  function handleToggleDay(key: string, checked: boolean) {
    if (!checked && runDays.length <= 1) return;
    setRunDays(checked ? [...runDays, key] : runDays.filter((d) => d !== key));
  }

  async function handleSave() {
    setSaving(true);
    setError(null);
    setSaved(false);
    try {
      const fresh = await updateAgentConfig({ runAt, runDays });
      onChange(fresh);
      setRunAt(fresh.runAt);
      setRunDays(fresh.runDays);
      setSaved(true);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Couldn't save the schedule.");
    } finally {
      setSaving(false);
    }
  }

  return (
    <Section
      title="Schedule"
      description="Changes take effect within about five minutes; the agent re-reads its schedule between runs."
    >
      <Stack direction="row" spacing={1} sx={{ flexWrap: "wrap" }}>
        {runAt.map((time) => (
          <Chip
            key={time}
            variant="outlined"
            label={time}
            onDelete={runAt.length > 1 ? () => handleRemoveTime(time) : undefined}
          />
        ))}
      </Stack>
      <Stack direction="row" spacing={1} sx={{ alignItems: "flex-start" }}>
        <TextField
          size="small"
          label="Add run time"
          placeholder="HH:MM"
          value={newTime}
          onChange={(e) => {
            setNewTime(e.target.value);
            setTimeError(null);
          }}
          error={!!timeError}
          helperText={timeError || undefined}
        />
        <Button variant="outlined" onClick={handleAddTime} disabled={!newTime}>
          Add
        </Button>
      </Stack>
      <Stack direction="row" spacing={1} sx={{ flexWrap: "wrap" }}>
        {WEEKDAYS.map((day) => (
          <FormControlLabel
            key={day.key}
            control={
              <Checkbox
                checked={runDays.includes(day.key)}
                onChange={(e) => handleToggleDay(day.key, e.target.checked)}
              />
            }
            label={day.label}
          />
        ))}
      </Stack>
      <Box>
        <Button variant="contained" onClick={handleSave} disabled={saving}>
          {saving && <ButtonSpinner />}
          {saving ? "Saving…" : "Save schedule"}
        </Button>
      </Box>
      {error && <Alert severity="error">{error}</Alert>}
      {saved && !error && <Alert severity="success">Schedule saved.</Alert>}
    </Section>
  );
}

/** Editable text-shaped mirror of a JobProfile: multi-item fields are held as
 * raw comma-separated text while being edited, and nullable numeric/string
 * fields are held as text too (blank means "unset" — the criterion is off).
 * Converted to/from JobProfile only at the section's load/save boundary. */
interface ProfileDraft {
  name: string;
  enabled: boolean;
  keywordsText: string;
  locationsText: string;
  preferredSourcesText: string;
  remoteModel: string;
  employmentCountry: string;
  eorAllowed: "" | "true" | "false";
  requireEntityVerification: boolean;
  salaryFloor: string;
  salaryAskMin: string;
  salaryAskMax: string;
  /** Carried through unedited so saving a profile cannot reset a hand-set currency. */
  currency: string;
  workingLanguage: string;
  glassdoorMin: string;
  glassdoorMinReviews: string;
  acceptedRoleTypesText: string;
  rejectedRoleTypesText: string;
}

function listToText(values: string[]): string {
  return values.join(", ");
}

function textToList(text: string): string[] {
  return text
    .split(",")
    .map((s) => s.trim())
    .filter(Boolean);
}

function numberToText(n: number | null): string {
  return n === null ? "" : String(n);
}

function textToIntOrNull(text: string): number | null {
  const t = text.trim();
  if (!t) return null;
  const n = Number(t);
  return Number.isFinite(n) ? Math.trunc(n) : null;
}

function textToFloatOrNull(text: string): number | null {
  const t = text.trim();
  if (!t) return null;
  const n = Number(t);
  return Number.isFinite(n) ? n : null;
}

function profileToDraft(p: JobProfile): ProfileDraft {
  return {
    name: p.name,
    enabled: p.enabled,
    keywordsText: listToText(p.keywords),
    locationsText: listToText(p.locations),
    preferredSourcesText: listToText(p.preferredSources),
    remoteModel: p.remoteModel ?? "",
    employmentCountry: p.employmentCountry ?? "",
    eorAllowed: p.eorAllowed === null ? "" : p.eorAllowed ? "true" : "false",
    requireEntityVerification: p.requireEntityVerification,
    salaryFloor: numberToText(p.salaryFloor),
    salaryAskMin: numberToText(p.salaryAskMin),
    salaryAskMax: numberToText(p.salaryAskMax),
    currency: p.currency || "EUR",
    workingLanguage: p.workingLanguage ?? "",
    glassdoorMin: numberToText(p.glassdoorMin),
    glassdoorMinReviews: numberToText(p.glassdoorMinReviews),
    acceptedRoleTypesText: listToText(p.acceptedRoleTypes),
    rejectedRoleTypesText: listToText(p.rejectedRoleTypes),
  };
}

function emptyDraft(): ProfileDraft {
  return {
    name: "New profile",
    enabled: true,
    keywordsText: "",
    locationsText: "",
    preferredSourcesText: "",
    remoteModel: "remote",
    employmentCountry: "Germany",
    eorAllowed: "false",
    requireEntityVerification: true,
    salaryFloor: "85000",
    salaryAskMin: "95000",
    salaryAskMax: "110000",
    currency: "EUR",
    workingLanguage: "English",
    glassdoorMin: "3.5",
    glassdoorMinReviews: "20",
    acceptedRoleTypesText: "agentic / AI engineering, data engineering",
    rejectedRoleTypesText: "generic full-stack, frontend, SRE, Java-heavy backend",
  };
}

function draftToProfile(d: ProfileDraft): JobProfile {
  return {
    name: d.name.trim(),
    enabled: d.enabled,
    keywords: textToList(d.keywordsText),
    locations: textToList(d.locationsText),
    preferredSources: textToList(d.preferredSourcesText),
    remoteModel: d.remoteModel.trim() || null,
    employmentCountry: d.employmentCountry.trim() || null,
    eorAllowed: d.eorAllowed === "" ? null : d.eorAllowed === "true",
    requireEntityVerification: d.requireEntityVerification,
    salaryFloor: textToIntOrNull(d.salaryFloor),
    salaryAskMin: textToIntOrNull(d.salaryAskMin),
    salaryAskMax: textToIntOrNull(d.salaryAskMax),
    currency: d.currency.trim() || "EUR",
    workingLanguage: d.workingLanguage.trim() || null,
    glassdoorMin: textToFloatOrNull(d.glassdoorMin),
    glassdoorMinReviews: textToIntOrNull(d.glassdoorMinReviews),
    acceptedRoleTypes: textToList(d.acceptedRoleTypesText),
    rejectedRoleTypes: textToList(d.rejectedRoleTypesText),
  };
}

/** Checks a salary-like field's text is either blank or a positive integer.
 * Returns an error message naming `label`, or null if the field is fine. */
function validateSalaryField(text: string, label: string): string | null {
  const n = textToIntOrNull(text);
  if (n !== null && n <= 0) return `${label} must be > 0`;
  return null;
}

/** Validates a set of profile drafts before they're sent to the API.
 * Returns a short message naming the first rule violated, or null if every
 * draft is well-formed. Checked in order: non-empty/unique names, positive
 * salary fields, salary ordering (floor <= ask min <= ask max), and a
 * glassdoor rating within [0, 5]. */
function validateDrafts(drafts: ProfileDraft[]): string | null {
  const seenNames = new Set<string>();
  for (const draft of drafts) {
    const name = draft.name.trim();
    if (!name) return "Profile name is required";
    if (seenNames.has(name)) return `Duplicate profile name: ${name}`;
    seenNames.add(name);

    const salaryError =
      validateSalaryField(draft.salaryFloor, "Salary floor") ||
      validateSalaryField(draft.salaryAskMin, "Salary ask minimum") ||
      validateSalaryField(draft.salaryAskMax, "Salary ask maximum");
    if (salaryError) return salaryError;

    const floor = textToIntOrNull(draft.salaryFloor);
    const askMin = textToIntOrNull(draft.salaryAskMin);
    const askMax = textToIntOrNull(draft.salaryAskMax);
    if (floor !== null && askMin !== null && floor > askMin) {
      return "Salary floor must be <= ask minimum";
    }
    if (askMin !== null && askMax !== null && askMin > askMax) {
      return "Salary ask minimum must be <= ask maximum";
    }

    const glassdoorMin = textToFloatOrNull(draft.glassdoorMin);
    if (glassdoorMin !== null && (glassdoorMin < 0 || glassdoorMin > 5)) {
      return "Glassdoor min rating must be 0-5";
    }
  }
  return null;
}

/** Job search profiles: each is a card of search criteria the agent matches
 * postings against, plus the two run-shaping numbers (cooldown, per-run cap)
 * that live alongside them on AgentConfig. Multi-item fields (keywords,
 * locations, preferred sources, role types) are edited as comma-separated
 * text; a blank field means that criterion is off. One explicit Save button
 * PUTs only `profiles`/`cooldownDays`/`maxApplicationsPerRun`, so it never
 * touches the schedule or blocklist sections' fields. */
function ProfilesSection({
  config,
  onChange,
}: {
  config: AgentConfig;
  onChange: (c: AgentConfig) => void;
}) {
  const [drafts, setDrafts] = useState<ProfileDraft[]>(() => config.profiles.map(profileToDraft));
  const [cooldownDays, setCooldownDays] = useState(numberToText(config.cooldownDays));
  const [maxApplicationsPerRun, setMaxApplicationsPerRun] = useState(
    numberToText(config.maxApplicationsPerRun),
  );
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [saved, setSaved] = useState(false);

  function updateDraft(index: number, patch: Partial<ProfileDraft>) {
    setDrafts((cur) => cur.map((d, i) => (i === index ? { ...d, ...patch } : d)));
  }

  function handleAdd() {
    setDrafts((cur) => [...cur, emptyDraft()]);
  }

  function handleRemove(index: number) {
    setDrafts((cur) => cur.filter((_, i) => i !== index));
  }

  async function handleSave() {
    const validationError = validateDrafts(drafts);
    if (validationError) {
      setError(validationError);
      setSaved(false);
      return;
    }
    setSaving(true);
    setError(null);
    setSaved(false);
    try {
      const fresh = await updateAgentConfig({
        profiles: drafts.map(draftToProfile),
        cooldownDays: textToIntOrNull(cooldownDays),
        maxApplicationsPerRun: textToIntOrNull(maxApplicationsPerRun),
      });
      onChange(fresh);
      setDrafts(fresh.profiles.map(profileToDraft));
      setCooldownDays(numberToText(fresh.cooldownDays));
      setMaxApplicationsPerRun(numberToText(fresh.maxApplicationsPerRun));
      setSaved(true);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Couldn't save the job profiles.");
    } finally {
      setSaving(false);
    }
  }

  return (
    <Section
      title="Job profiles"
      description="Search criteria the agent matches postings against. A blank field means that criterion is off — the agent won't filter on it."
    >
      <Stack spacing={2}>
        {drafts.map((draft, index) => (
          <Card key={index} variant="outlined">
            <CardContent>
              <Stack spacing={2}>
                <Stack direction="row" spacing={2} sx={{ alignItems: "center", flexWrap: "wrap" }}>
                  <TextField
                    label="Name"
                    size="small"
                    value={draft.name}
                    onChange={(e) => updateDraft(index, { name: e.target.value })}
                  />
                  <FormControlLabel
                    control={
                      <Checkbox
                        checked={draft.enabled}
                        onChange={(e) => updateDraft(index, { enabled: e.target.checked })}
                      />
                    }
                    label="Enabled"
                  />
                  <Button variant="outlined" color="error" onClick={() => handleRemove(index)}>
                    Remove
                  </Button>
                </Stack>
                <TextField
                  label="Keywords"
                  size="small"
                  fullWidth
                  value={draft.keywordsText}
                  onChange={(e) => updateDraft(index, { keywordsText: e.target.value })}
                  helperText="Comma-separated. Blank means no keyword filter."
                />
                <TextField
                  label="Locations"
                  size="small"
                  fullWidth
                  value={draft.locationsText}
                  onChange={(e) => updateDraft(index, { locationsText: e.target.value })}
                  helperText="Comma-separated. Blank means no location filter."
                />
                <TextField
                  label="Preferred sources"
                  size="small"
                  fullWidth
                  value={draft.preferredSourcesText}
                  onChange={(e) => updateDraft(index, { preferredSourcesText: e.target.value })}
                  helperText="Comma-separated. Blank means no source preference."
                />
                <TextField
                  label="Accepted role types"
                  size="small"
                  fullWidth
                  value={draft.acceptedRoleTypesText}
                  onChange={(e) => updateDraft(index, { acceptedRoleTypesText: e.target.value })}
                  helperText="Comma-separated. Blank means all role types accepted."
                />
                <TextField
                  label="Rejected role types"
                  size="small"
                  fullWidth
                  value={draft.rejectedRoleTypesText}
                  onChange={(e) => updateDraft(index, { rejectedRoleTypesText: e.target.value })}
                  helperText="Comma-separated. Blank means none rejected."
                />
                <Stack direction="row" spacing={2} sx={{ flexWrap: "wrap" }}>
                  <TextField
                    label="Remote model"
                    size="small"
                    value={draft.remoteModel}
                    onChange={(e) => updateDraft(index, { remoteModel: e.target.value })}
                  />
                  <TextField
                    label="Employment country"
                    size="small"
                    value={draft.employmentCountry}
                    onChange={(e) => updateDraft(index, { employmentCountry: e.target.value })}
                  />
                  <TextField
                    label="Working language"
                    size="small"
                    value={draft.workingLanguage}
                    onChange={(e) => updateDraft(index, { workingLanguage: e.target.value })}
                  />
                  <TextField
                    select
                    label="EOR allowed"
                    size="small"
                    value={draft.eorAllowed}
                    onChange={(e) =>
                      updateDraft(index, {
                        eorAllowed: e.target.value as ProfileDraft["eorAllowed"],
                      })
                    }
                    sx={{ minWidth: 140 }}
                  >
                    <MenuItem value="">Not set</MenuItem>
                    <MenuItem value="true">Allowed</MenuItem>
                    <MenuItem value="false">Not allowed</MenuItem>
                  </TextField>
                </Stack>
                <Stack direction="row" spacing={2} sx={{ flexWrap: "wrap" }}>
                  <TextField
                    label="Salary floor"
                    size="small"
                    value={draft.salaryFloor}
                    onChange={(e) => updateDraft(index, { salaryFloor: e.target.value })}
                  />
                  <TextField
                    label="Salary ask min"
                    size="small"
                    value={draft.salaryAskMin}
                    onChange={(e) => updateDraft(index, { salaryAskMin: e.target.value })}
                  />
                  <TextField
                    label="Salary ask max"
                    size="small"
                    value={draft.salaryAskMax}
                    onChange={(e) => updateDraft(index, { salaryAskMax: e.target.value })}
                  />
                  <TextField
                    label="Glassdoor min"
                    size="small"
                    value={draft.glassdoorMin}
                    onChange={(e) => updateDraft(index, { glassdoorMin: e.target.value })}
                  />
                  <TextField
                    label="Glassdoor min reviews"
                    size="small"
                    value={draft.glassdoorMinReviews}
                    onChange={(e) => updateDraft(index, { glassdoorMinReviews: e.target.value })}
                  />
                </Stack>
                <FormControlLabel
                  control={
                    <Checkbox
                      checked={draft.requireEntityVerification}
                      onChange={(e) =>
                        updateDraft(index, { requireEntityVerification: e.target.checked })
                      }
                    />
                  }
                  label="Require entity verification"
                />
              </Stack>
            </CardContent>
          </Card>
        ))}
      </Stack>
      <Box>
        <Button variant="outlined" onClick={handleAdd}>
          Add profile
        </Button>
      </Box>
      <Stack direction="row" spacing={2} sx={{ flexWrap: "wrap" }}>
        <TextField
          label="Cooldown days"
          size="small"
          value={cooldownDays}
          onChange={(e) => setCooldownDays(e.target.value)}
          helperText="Days a rejected or applied-to company stays blocked. Blank uses the default (90); 0 disables."
        />
        <TextField
          label="Max applications per run"
          size="small"
          value={maxApplicationsPerRun}
          onChange={(e) => setMaxApplicationsPerRun(e.target.value)}
          helperText="Saved here but not yet wired into agent runs — the container's MAX_APPLICATIONS_PER_RUN env var sets the actual per-run cap."
        />
      </Stack>
      <Box>
        <Button variant="contained" onClick={handleSave} disabled={saving}>
          {saving && <ButtonSpinner />}
          {saving ? "Saving…" : "Save profiles"}
        </Button>
      </Box>
      {error && <Alert severity="error">{error}</Alert>}
      {saved && !error && <Alert severity="success">Job profiles saved.</Alert>}
    </Section>
  );
}

/** Blocked-company list. Saves immediately on add/remove — no separate Save
 * button, since each change is a small, self-contained edit. */
function BlocklistSection({
  config,
  onChange,
}: {
  config: AgentConfig;
  onChange: (c: AgentConfig) => void;
}) {
  const [newCompany, setNewCompany] = useState("");
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function persist(blockedCompanies: string[]) {
    setSaving(true);
    setError(null);
    try {
      const fresh = await updateAgentConfig({ blockedCompanies });
      onChange(fresh);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Couldn't update the blocklist.");
    } finally {
      setSaving(false);
    }
  }

  function handleAdd() {
    const trimmed = newCompany.trim();
    if (!trimmed) return;
    const exists = config.blockedCompanies.some(
      (c) => c.toLowerCase() === trimmed.toLowerCase(),
    );
    if (exists) {
      setNewCompany("");
      return;
    }
    setNewCompany("");
    persist([...config.blockedCompanies, trimmed]);
  }

  function handleRemove(company: string) {
    persist(config.blockedCompanies.filter((c) => c !== company));
  }

  return (
    <Section
      title="Blocked companies"
      description="The agent will never apply to a blocked company. Matching is by exact name, ignoring case."
    >
      <Stack direction="row" spacing={1} sx={{ flexWrap: "wrap" }}>
        {config.blockedCompanies.map((company) => (
          <Chip
            key={company}
            variant="outlined"
            label={company}
            onDelete={() => handleRemove(company)}
            disabled={saving}
          />
        ))}
      </Stack>
      <Stack direction="row" spacing={1}>
        <TextField
          size="small"
          label="Add company"
          value={newCompany}
          onChange={(e) => setNewCompany(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter" && !saving) handleAdd();
          }}
        />
        <Button variant="outlined" onClick={handleAdd} disabled={saving || !newCompany.trim()}>
          Add
        </Button>
      </Stack>
      {error && <Alert severity="error">{error}</Alert>}
    </Section>
  );
}

/** The 20 ATS answers and cover-letter claim sources. Each has its own MUI
 * TextField and is sent on Save. Salary is absent; canonicalCvAssetId is never
 * sent. The agent uses these; the cover-letter writer sources facts from them. */
function ProfileAnswersSection({
  answers,
  onChange,
}: {
  answers: ProfileAnswers;
  onChange: (a: ProfileAnswers) => void;
}) {
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [saved, setSaved] = useState(false);

  const ANSWER_FIELDS = [
    { key: "name" as const, label: "Name" },
    { key: "email" as const, label: "Email" },
    { key: "phone" as const, label: "Phone" },
    { key: "linkedin" as const, label: "LinkedIn" },
    { key: "github" as const, label: "GitHub" },
    { key: "website" as const, label: "Website" },
    { key: "locationPreference" as const, label: "Location preference" },
    { key: "workAuthorisation" as const, label: "Work authorisation" },
    { key: "noticePeriod" as const, label: "Notice period" },
    { key: "requiresSponsorship" as const, label: "Requires sponsorship" },
    {
      key: "authorizedNonGermanCountry" as const,
      label: "Authorised in a non-German country",
    },
    { key: "languages" as const, label: "Languages" },
    { key: "highestRelevantDegree" as const, label: "Highest relevant degree" },
    { key: "otherDegree" as const, label: "Other degree" },
    { key: "csDegree" as const, label: "CS degree" },
    { key: "gpa" as const, label: "GPA" },
    { key: "gender" as const, label: "Gender" },
    { key: "yearsOfExperience" as const, label: "Years of experience" },
    { key: "currentRole" as const, label: "Current role" },
    { key: "howDidYouHear" as const, label: "How did you hear about us" },
  ];

  async function handleSave() {
    setSaving(true);
    setError(null);
    setSaved(false);
    try {
      const body: Partial<ProfileAnswers> = {};
      for (const field of ANSWER_FIELDS) {
        body[field.key] = answers[field.key];
      }
      const fresh = await saveProfileAnswers(body);
      onChange(fresh);
      setSaved(true);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Couldn't save the profile answers.");
    } finally {
      setSaving(false);
    }
  }

  return (
    <Section
      title="Profile answers"
      description="Answers to ATS screening questions (name, email, location, work rights, etc.) which the unattended application agent submits on your behalf and the cover-letter writer receives as allowed claim sources. Keep them accurate. Salary is not one of them: the agent derives its figure from the matched job profile's ask band below."
    >
      {ANSWER_FIELDS.map((field) => (
        <TextField
          key={field.key}
          fullWidth
          label={field.label}
          value={answers[field.key]}
          onChange={(e) =>
            onChange({
              ...answers,
              [field.key]: e.target.value,
            })
          }
        />
      ))}
      <Box>
        <Button variant="contained" onClick={handleSave} disabled={saving}>
          {saving && <ButtonSpinner />}
          {saving ? "Saving…" : "Save answers"}
        </Button>
      </Box>
      {error && <Alert severity="error">{error}</Alert>}
      {saved && !error && <Alert severity="success">Profile answers saved.</Alert>}
    </Section>
  );
}


