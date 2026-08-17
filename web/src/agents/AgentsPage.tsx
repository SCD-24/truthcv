import { useEffect, useState } from "react";
import Box from "@mui/material/Box";
import Stack from "@mui/material/Stack";
import Paper from "@mui/material/Paper";
import Button from "@mui/material/Button";
import IconButton from "@mui/material/IconButton";
import DeleteOutlineIcon from "@mui/icons-material/DeleteOutlined";
import ArrowBackIcon from "@mui/icons-material/ArrowBack";
import Alert from "@mui/material/Alert";
import Switch from "@mui/material/Switch";
import FormControlLabel from "@mui/material/FormControlLabel";
import Checkbox from "@mui/material/Checkbox";
import TextField from "@mui/material/TextField";
import Typography from "@mui/material/Typography";
import CircularProgress from "@mui/material/CircularProgress";
import Table from "@mui/material/Table";
import TableBody from "@mui/material/TableBody";
import TableCell from "@mui/material/TableCell";
import TableHead from "@mui/material/TableHead";
import TableRow from "@mui/material/TableRow";
import Chip from "@mui/material/Chip";
import Tooltip from "@mui/material/Tooltip";
import {
  deleteScreening,
  getAgentConfig,
  getProfileAnswers,
  listScreenings,
  saveProfileAnswers,
  updateAgentConfig,
} from "../api/client";
import { ButtonSpinner } from "../components/ButtonSpinner";
import { isCooldownActive } from "../settings/cooldown";
import { lastAgentActivity } from "../settings/agentActivity";
import { isValidRunTime, WEEKDAYS } from "./schedule";
import type { AgentConfig, ProfileAnswers, ScreeningRecord } from "../api/types";

/** The five canonical ATS answers before they're loaded from the server. */
const EMPTY_ANSWERS: ProfileAnswers = {
  phone: "",
  workAuthorisation: "",
  salaryExpectation: "",
  noticePeriod: "",
  locationPreference: "",
  canonicalCvAssetId: null,
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

/** How a cooldown reads in the table: the active/expired/none label the chip
 * carries, kept separate from the pure isCooldownActive predicate. */
function cooldownLabel(record: ScreeningRecord, active: boolean): string {
  if (active) return `Until ${record.cooldownExpires}`;
  return record.cooldownExpires ? "Expired" : "No cooldown";
}

/** One rejected-target row: company/reason, role, verdict, why it failed, its
 * cooldown state, and a delete control to un-block it. */
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

/**
 * The Agents page — enable/disable the unattended application agent, edit its
 * run schedule and blocklist, edit the ATS profile answers it submits, and
 * review/clear the screening & cooldown ledger. Reached from the rail
 * (wired in a later task); `onBack` returns to the wizard step left behind.
 *
 * Each section owns its own error/success state and saves independently, so a
 * failure in one (e.g. a bad schedule save) never blocks or clobbers another.
 */
export function AgentsPage({ onBack }: { onBack: () => void }) {
  const [config, setConfig] = useState<AgentConfig | null>(null);
  const [answers, setAnswers] = useState<ProfileAnswers>(EMPTY_ANSWERS);
  const [screenings, setScreenings] = useState<ScreeningRecord[]>([]);
  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState<string | null>(null);

  useEffect(() => {
    let alive = true;
    Promise.all([getAgentConfig(), getProfileAnswers(), listScreenings()])
      .then(([c, a, sc]) => {
        if (!alive) return;
        setConfig(c);
        setAnswers(a);
        setScreenings(sc);
      })
      .catch((e: unknown) =>
        setLoadError(e instanceof Error ? e.message : "Couldn't load the agent's configuration."),
      )
      .finally(() => alive && setLoading(false));
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
          <EnabledSection config={config} onChange={setConfig} />
          <ScheduleSection config={config} onChange={setConfig} />
          <BlocklistSection config={config} onChange={setConfig} />
          <ProfileAnswersSection answers={answers} onChange={setAnswers} />
          <ScreeningsSection screenings={screenings} onChange={setScreenings} />
        </Stack>
      ) : null}
    </Box>
  );
}

/** Agent enabled/disabled toggle. Optimistic — flips immediately, reverts and
 * surfaces an error if the PUT fails. */
function EnabledSection({
  config,
  onChange,
}: {
  config: AgentConfig;
  onChange: (c: AgentConfig) => void;
}) {
  const [error, setError] = useState<string | null>(null);

  async function handleToggle(enabled: boolean) {
    const previous = config;
    setError(null);
    onChange({ ...config, enabled });
    try {
      const fresh = await updateAgentConfig({ enabled });
      onChange(fresh);
    } catch (e) {
      onChange(previous);
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
            if (e.key === "Enter") handleAdd();
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

/** The five ATS answers, moved verbatim from SettingsModal with their own
 * Save that PUTs only these five keys (a partial body). */
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

  async function handleSave() {
    setSaving(true);
    setError(null);
    setSaved(false);
    try {
      const fresh = await saveProfileAnswers({
        phone: answers.phone,
        workAuthorisation: answers.workAuthorisation,
        salaryExpectation: answers.salaryExpectation,
        noticePeriod: answers.noticePeriod,
        locationPreference: answers.locationPreference,
      });
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
      description="The canonical answers the unattended application agent types into ATS forms when it submits on your behalf. Keep them accurate — they go out with every application."
    >
      <TextField
        fullWidth
        label="Phone"
        value={answers.phone}
        onChange={(e) => onChange({ ...answers, phone: e.target.value })}
        helperText="What the agent types into ATS phone fields."
      />
      <TextField
        fullWidth
        label="Work authorisation"
        value={answers.workAuthorisation}
        onChange={(e) => onChange({ ...answers, workAuthorisation: e.target.value })}
        helperText='What the agent types into ATS work-authorisation questions — e.g. "Authorised to work in the UK, no sponsorship required."'
      />
      <TextField
        fullWidth
        label="Salary expectation"
        value={answers.salaryExpectation}
        onChange={(e) => onChange({ ...answers, salaryExpectation: e.target.value })}
        helperText="What the agent types into ATS salary-expectation fields."
      />
      <TextField
        fullWidth
        label="Notice period"
        value={answers.noticePeriod}
        onChange={(e) => onChange({ ...answers, noticePeriod: e.target.value })}
        helperText="What the agent types into ATS notice-period fields."
      />
      <TextField
        fullWidth
        label="Location preference"
        value={answers.locationPreference}
        onChange={(e) => onChange({ ...answers, locationPreference: e.target.value })}
        helperText="What the agent types into ATS location/relocation fields."
      />
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

/** The screening/cooldown ledger, moved verbatim from SettingsModal. */
function ScreeningsSection({
  screenings,
  onChange,
}: {
  screenings: ScreeningRecord[];
  onChange: (s: ScreeningRecord[]) => void;
}) {
  const [deletingId, setDeletingId] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const last = lastAgentActivity(screenings);
  const lastLabel = last ? new Date(last).toLocaleDateString() : null;

  async function handleDelete(id: string) {
    setDeletingId(id);
    setError(null);
    try {
      await deleteScreening(id);
      onChange(screenings.filter((r) => r.id !== id));
    } catch (e) {
      setError(e instanceof Error ? e.message : "Couldn't delete the screening record.");
    } finally {
      setDeletingId(null);
    }
  }

  return (
    <Section
      title="Screening & cooldowns"
      description="Targets the unattended application agent rejected, why, and how long each stays in cooldown before it's reconsidered. Delete a record to un-block a target immediately."
    >
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
                deleting={deletingId === record.id}
                onDelete={handleDelete}
              />
            ))}
          </TableBody>
        </Table>
      )}
      {error && <Alert severity="error">{error}</Alert>}
    </Section>
  );
}
