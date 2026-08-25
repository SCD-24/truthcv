import { useEffect, useRef, useState } from "react";
import Box from "@mui/material/Box";
import Stack from "@mui/material/Stack";
import Paper from "@mui/material/Paper";
import Card from "@mui/material/Card";
import CardContent from "@mui/material/CardContent";
import Button from "@mui/material/Button";
import ArrowBackIcon from "@mui/icons-material/ArrowBack";
import Alert from "@mui/material/Alert";
import FormControlLabel from "@mui/material/FormControlLabel";
import Slider from "@mui/material/Slider";
import Checkbox from "@mui/material/Checkbox";
import TextField from "@mui/material/TextField";
import MenuItem from "@mui/material/MenuItem";
import Typography from "@mui/material/Typography";
import CircularProgress from "@mui/material/CircularProgress";
import Chip from "@mui/material/Chip";
import Link from "@mui/material/Link";
import {
  getAgentConfig,
  cancelAgentRun,
  getAgentStatus,
  getProfileAnswers,
  getRouting,
  listConnections,
  listRuns,
  saveProfileAnswers,
  triggerAgentRun,
  updateAgentConfig,
  updateRouting,
} from "../api/client";
import { ButtonSpinner } from "../components/ButtonSpinner";
import { ModelRoutePicker } from "../settings/ModelRoutePicker";
import { SettingsModal } from "../settings/SettingsModal";
import { isValidRunTime, WEEKDAYS } from "./schedule";
import { JobBoardsSection } from "./JobBoardsSection";
import type {
  AgentConfig,
  AgentStatus,
  ConnectionStatus,
  JobProfile,
  ProfileAnswers,
  Routing,
  RunRecord,
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
  workAuthorisationNote: "",
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
  // Set when the user asks to edit a setting that lives in the Settings
  // modal (e.g. the cooldown windows) — opens it scrolled to that section.
  const [settingsSection, setSettingsSection] = useState<"job-search-policy" | null>(null);

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
          <ModeSection
            config={config}
            onChange={(updater) => setConfig((cur) => (cur ? updater(cur) : cur))}
          />
          <RunNowSection agentEnabled={config.enabled} />
          <RecentRunsSection />
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
          <ProfilesSection
            config={config}
            onChange={setConfig}
            onOpenSettings={() => setSettingsSection("job-search-policy")}
          />
          <JobBoardsSection config={config} onChange={setConfig} />
          <BlocklistSection config={config} onChange={setConfig} />
          {settingsSection && (
            <SettingsModal
              initialSection={settingsSection}
              onClose={() => setSettingsSection(null)}
            />
          )}
          <CanonicalCvSection answers={answers} />
          <ProfileAnswersSection answers={answers} onChange={setAnswers} />
        </Stack>
      ) : null}
    </Box>
  );
}

/** Polling interval (ms) for the run-now status poller in idle state. */
const STATUS_POLL_IDLE_MS = 10_000;
/** Faster polling interval used while a run is active or was just triggered. */
const STATUS_POLL_ACTIVE_MS = 2_000;

/**
 * Run now control with live running/idle status.
 *
 * Polls GET /api/agent/status every 10 s in idle state, every 2 s while a run
 * is active. Uses a ref to track the current interval so that pace changes
 * (active → idle) never leak an interval. Clears on unmount. Inline 503 error
 * rather than a global alert — the agent container may simply be stopped.
 */
function RunNowSection({ agentEnabled }: { agentEnabled: boolean }) {
  const [agentStatus, setAgentStatus] = useState<AgentStatus | null>(null);
  const [triggering, setTriggering] = useState(false);
  const [cancelling, setCancelling] = useState(false);
  const [unreachable, setUnreachable] = useState<string | null>(null);

  // Ref always holds the *current* active interval ID so the cleanup function
  // clears whichever interval is live at unmount time, including any that were
  // started by pace changes inside the poll callback.
  const pollIdRef = useRef<ReturnType<typeof setInterval> | null>(null);
  // Mounted-ness has to outlive the effect closure: `setPoll` is called from
  // async continuations (the cancel POST, the status poll) that can resolve
  // after unmount. Without this an interval was installed on a dead component
  // AFTER cleanup had already run, so nothing could ever clear it — a 2-second
  // poll for the rest of the session.
  const aliveRef = useRef(true);

  /** Replace the current poll with one at a new interval, unless unmounted. */
  function setPoll(intervalMs: number) {
    if (pollIdRef.current != null) clearInterval(pollIdRef.current);
    pollIdRef.current = null;
    if (!aliveRef.current) return;
    pollIdRef.current = setInterval(() => {
      getAgentStatus()
        .then((s) => {
          setAgentStatus(s);
          setUnreachable(null);
          // The run is gone, so a cancel of it is no longer in progress —
          // clear the local flag or the button stays stuck on "Stopping…".
          if (!s.running) setCancelling(false);
          // Slow down once the run finishes
          if (!s.running && intervalMs === STATUS_POLL_ACTIVE_MS) {
            setPoll(STATUS_POLL_IDLE_MS);
          }
        })
        .catch((e: unknown) => {
          setUnreachable(e instanceof Error ? e.message : "Agent service unreachable");
        });
    }, intervalMs);
  }

  useEffect(() => {
    aliveRef.current = true;
    let alive = true;

    // Kick off an immediate status fetch, then start the poller
    getAgentStatus()
      .then((s) => {
        if (!alive) return;
        setAgentStatus(s);
        setUnreachable(null);
        setPoll(s.running ? STATUS_POLL_ACTIVE_MS : STATUS_POLL_IDLE_MS);
      })
      .catch((e: unknown) => {
        if (!alive) return;
        setUnreachable(e instanceof Error ? e.message : "Agent service unreachable");
        // Keep polling so we recover when the container comes back up
        setPoll(STATUS_POLL_IDLE_MS);
      });

    return () => {
      alive = false;
      aliveRef.current = false;
      if (pollIdRef.current != null) clearInterval(pollIdRef.current);
      // Null it too: a later `setPoll` from an in-flight promise would
      // otherwise clear an already-cleared id and install a fresh interval.
      pollIdRef.current = null;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const running = agentStatus?.running ?? false;
  // The supervisor's own cancelling flag outlives this component's local one
  // across a remount, so a stopping run still reads as stopping after a reload.
  const stopping = cancelling || (agentStatus?.cancelling ?? false);
  const buttonDisabled = !agentEnabled || triggering || running;

  async function handleCancel() {
    setCancelling(true);
    setUnreachable(null);
    try {
      await cancelAgentRun();
      // Keep polling at the active pace: the run is signalled, not yet gone,
      // and only the status poll can tell us when it has actually exited.
      setPoll(STATUS_POLL_ACTIVE_MS);
    } catch (e: unknown) {
      setUnreachable(e instanceof Error ? e.message : "Agent service unreachable");
      setCancelling(false);
    }
  }

  async function handleRunNow() {
    setTriggering(true);
    setUnreachable(null);
    try {
      const result = await triggerAgentRun();
      if (result.running) {
        setAgentStatus((prev) =>
          prev
            ? { ...prev, running: true }
            : {
                running: true,
                cancelling: false,
                lastStartedAt: null,
                lastFinishedAt: null,
                lastExitCode: null,
                lastCancelled: false,
              },
        );
        // Poll faster while the run is active
        setPoll(STATUS_POLL_ACTIVE_MS);
      }
    } catch (e: unknown) {
      setUnreachable(e instanceof Error ? e.message : "Agent service unreachable");
    } finally {
      setTriggering(false);
    }
  }

  return (
    <Section
      title="Run now"
      description="Trigger an immediate agent run outside the scheduled slots, or stop the one in progress."
    >
      <Stack direction="row" spacing={2} sx={{ alignItems: "center" }}>
        {agentEnabled ? (
          <Button
            variant="outlined"
            onClick={handleRunNow}
            disabled={buttonDisabled}
            aria-label="Run agent now"
          >
            {(triggering || running) && <ButtonSpinner />}
            {running ? "Running…" : triggering ? "Starting…" : "Run now"}
          </Button>
        ) : (
          <Button variant="outlined" disabled aria-label="Run agent now">
            Run now
          </Button>
        )}
        {running && (
          <Button
            variant="outlined"
            color="warning"
            onClick={handleCancel}
            disabled={stopping}
            aria-label="Cancel agent run"
          >
            {stopping && <ButtonSpinner />}
            {stopping ? "Stopping…" : "Cancel run"}
          </Button>
        )}
        {agentStatus && !running && agentStatus.lastFinishedAt && (
          <Typography variant="body2" color="text.secondary">
            Last run {agentStatus.lastCancelled ? "cancelled" : "finished"} at{" "}
            {new Date(agentStatus.lastFinishedAt).toLocaleString(undefined, {
              dateStyle: "short",
              timeStyle: "short",
            })}
            {/* A cancelled run's non-zero exit is the cancel, not a failure. */}
            {!agentStatus.lastCancelled &&
              agentStatus.lastExitCode !== null &&
              agentStatus.lastExitCode !== 0 && (
                <> &mdash; exit&nbsp;{agentStatus.lastExitCode}</>
              )}
          </Typography>
        )}
      </Stack>
      {!agentEnabled && (
        <Typography variant="body2" color="text.secondary">
          Enable the agent above to trigger a run.
        </Typography>
      )}
      {unreachable && (
        <Alert severity="warning" sx={{ mt: 1 }}>
          {unreachable}
        </Alert>
      )}
    </Section>
  );
}

export { RecentRunsSection };

/** Lists recent agent runs with their honest coverage summary — how much of
 * the work each run actually got through, and where a partial run stopped.
 * Polls independently of RunNowSection's status poll so this list refreshes
 * without coupling to that component's pacing. */
function RecentRunsSection() {
  const [runs, setRuns] = useState<RunRecord[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let alive = true;

    function refresh() {
      listRuns(10)
        .then((rs) => {
          if (!alive) return;
          setRuns(rs);
          setError(null);
        })
        .catch((e: unknown) => {
          if (!alive) return;
          setError(e instanceof Error ? e.message : "Could not load recent runs");
        });
    }

    refresh();
    const id = setInterval(refresh, STATUS_POLL_IDLE_MS);
    return () => {
      alive = false;
      clearInterval(id);
    };
  }, []);

  return (
    <Section title="Recent runs" description="What each run covered, and where a partial run stopped.">
      {error && <Alert severity="warning">{error}</Alert>}
      {runs === null && !error && (
        <Typography variant="body2" color="text.secondary">
          Loading…
        </Typography>
      )}
      {runs !== null && runs.length === 0 && (
        <Typography variant="body2" color="text.secondary">
          No runs recorded yet.
        </Typography>
      )}
      {runs !== null && runs.length > 0 && (
        <Stack spacing={1}>
          {runs.map((run) => (
            <RunSummaryRow key={run.id} run={run} />
          ))}
        </Stack>
      )}
    </Section>
  );
}

function RunSummaryRow({ run }: { run: RunRecord }) {
  const isRunning = run.status === "running";
  const capLabel = run.applyCap > 0 ? `${run.applicationsSubmitted}/${run.applyCap}` : `${run.applicationsSubmitted}`;
  return (
    <Paper
      variant="outlined"
      sx={{ p: 1.5, borderColor: isRunning ? "info.main" : undefined }}
      aria-label={`Run ${run.id}`}
    >
      <Stack direction="row" spacing={1} sx={{ alignItems: "center", flexWrap: "wrap" }}>
        <Chip
          size="small"
          label={isRunning ? "Running" : run.status || "unknown"}
          color={isRunning ? "info" : run.status === "failed" ? "error" : "default"}
          variant={isRunning ? "filled" : "outlined"}
        />
        <Typography variant="body2" sx={{ fontFamily: "monospace" }}>
          {run.id}
        </Typography>
        <Typography variant="body2" color="text.secondary">
          {run.startedAt ? new Date(run.startedAt).toLocaleString() : ""}
          {run.finishedAt ? ` – ${new Date(run.finishedAt).toLocaleString()}` : ""}
        </Typography>
      </Stack>
      <Stack direction="row" spacing={2} sx={{ mt: 0.5, flexWrap: "wrap" }}>
        <Typography variant="caption" color="text.secondary">
          Postings seen: {run.postingsSeen}
        </Typography>
        <Typography variant="caption" color="text.secondary">
          Screenings recorded: {run.screeningsRecorded}
        </Typography>
        <Typography variant="caption" color="text.secondary">
          Blocked: {run.blockedCount}
        </Typography>
        <Typography variant="caption" color="text.secondary">
          Applied: {capLabel}
        </Typography>
        {run.overCapWrites > 0 && (
          <Typography variant="caption" color="warning.main">
            Over cap: {run.overCapWrites}
          </Typography>
        )}
      </Stack>
      {run.stoppedReason && (
        <Typography variant="caption" color="text.secondary" sx={{ display: "block", mt: 0.5 }}>
          Stopped: {run.stoppedReason}
        </Typography>
      )}
    </Paper>
  );
}

const MODES = ["off", "semi", "full"] as const;
type Mode = (typeof MODES)[number];

const MODE_HELP: Record<Mode, string> = {
  off: "Scheduled runs wake, log that the agent is off, and exit. Nothing is submitted.",
  semi: "The agent finds and screens roles, then waits. You draft the cover letter and approve; approved roles are applied on the next scheduled run.",
  full: "The agent finds, screens, writes the letter and applies on its own. Roles it cannot decide alone still wait for you.",
};

/** Agent autonomy slider. Optimistic — moves immediately on commit, reverts
 * and surfaces an error if the PUT fails.
 *
 * `onChange` takes an updater over the *current* config rather than a
 * snapshot, so the optimistic set and its revert only ever touch the
 * `mode` field against whatever the latest state is — a save from
 * another section (e.g. Schedule) that lands while this PUT is in flight
 * is never clobbered by a stale full-config revert.
 *
 * The network write happens on `onChangeCommitted`, not `onChange`: MUI's
 * `Slider` fires `onChange` for every mark the thumb crosses during a drag,
 * so wiring the PUT to `onChange` sends one request per intermediate mark,
 * unordered and uncancellable — a drag from full auto to off could land on
 * semi-auto if the requests resolve out of order. `onChangeCommitted` fires
 * once per interaction (drag release; each keypress is its own interaction
 * for the keyboard path), so exactly one PUT goes out per operator gesture,
 * carrying only the final value. `localIndex` tracks the thumb during the
 * drag so it still moves live; it is display-only and never itself triggers
 * a save. */
function ModeSection({
  config,
  onChange,
}: {
  config: AgentConfig;
  onChange: (updater: (prev: AgentConfig) => AgentConfig) => void;
}) {
  const [error, setError] = useState<string | null>(null);

  const configIndex = Math.max(0, MODES.indexOf(config.mode));
  const [localIndex, setLocalIndex] = useState(configIndex);

  // Keeps the thumb in sync when the mode changes for a reason other than
  // this control's own commit — the initial load, and a failed PUT's revert.
  useEffect(() => {
    setLocalIndex(configIndex);
  }, [configIndex]);

  async function handleMode(mode: Mode) {
    const previous = config.mode;
    setError(null);
    onChange((prev) => ({ ...prev, mode }));
    try {
      const fresh = await updateAgentConfig({ mode });
      onChange((prev) => ({ ...prev, mode: fresh.mode, enabled: fresh.enabled }));
    } catch (e) {
      onChange((prev) => ({ ...prev, mode: previous }));
      setError(e instanceof Error ? e.message : "Couldn't update the agent.");
    }
  }

  return (
    <Section title="Agent">
      <Slider
        value={localIndex}
        min={0}
        max={2}
        step={null}
        marks={[
          { value: 0, label: "Off" },
          { value: 1, label: "Semi-auto" },
          { value: 2, label: "Full auto" },
        ]}
        onChange={(_e, v) => setLocalIndex(v as number)}
        onChangeCommitted={(_e, v) => handleMode(MODES[v as number])}
        sx={{ maxWidth: 360, ml: 1 }}
        aria-label="Agent autonomy"
      />
      <Typography variant="body2" color="text.secondary">
        {MODE_HELP[config.mode]}
      </Typography>
      {error && <Alert severity="error">{error}</Alert>}
    </Section>
  );
}

/** The model the unattended agent runs on — an Anthropic-compatible-only
 * ModelRoutePicker
 * (the agent is a headless Claude Code process — it is the `claude` CLI that
 * drives the containerised Chromium in the sibling `browser` service over
 * MCP, so the only usable connections are the ones serving the Anthropic
 * Messages API: Anthropic itself and OpenRouter, which the CLI reaches via
 * ANTHROPIC_BASE_URL. codex and ollama offer an OpenAI-shaped surface only)
 * saving/clearing the `agent` route.
 * Cleared falls back to the container's ANTHROPIC_API_KEY. */
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
      filterCards={["claude", "openrouter"]}
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
  remoteModel: string;
  employmentCountry: string;
  eorAllowed: "" | "true" | "false";
  requireEntityVerification: boolean;
  salaryFloor: string;
  salaryAskMin: string;
  salaryAskMax: string;
  /** Carried through unedited so saving a profile cannot reset a hand-set
   * currency. Empty means the user has not configured one — there is no
   * regional default to fall back to. */
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
    remoteModel: p.remoteModel ?? "",
    employmentCountry: p.employmentCountry ?? "",
    eorAllowed: p.eorAllowed === null ? "" : p.eorAllowed ? "true" : "false",
    requireEntityVerification: p.requireEntityVerification,
    salaryFloor: numberToText(p.salaryFloor),
    salaryAskMin: numberToText(p.salaryAskMin),
    salaryAskMax: numberToText(p.salaryAskMax),
    currency: p.currency ?? "",
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
    remoteModel: "remote",
    employmentCountry: "Germany",
    eorAllowed: "false",
    requireEntityVerification: true,
    salaryFloor: "70000",
    salaryAskMin: "80000",
    salaryAskMax: "100000",
    // Deliberately blank: no regional default. The user states their own.
    currency: "",
    workingLanguage: "",
    glassdoorMin: "",
    glassdoorMinReviews: "",
    acceptedRoleTypesText: "",
    rejectedRoleTypesText: "",
  };
}

function draftToProfile(d: ProfileDraft): JobProfile {
  return {
    name: d.name.trim(),
    enabled: d.enabled,
    keywords: textToList(d.keywordsText),
    locations: textToList(d.locationsText),
    remoteModel: d.remoteModel.trim() || null,
    employmentCountry: d.employmentCountry.trim() || null,
    eorAllowed: d.eorAllowed === "" ? null : d.eorAllowed === "true",
    requireEntityVerification: d.requireEntityVerification,
    salaryFloor: textToIntOrNull(d.salaryFloor),
    salaryAskMin: textToIntOrNull(d.salaryAskMin),
    salaryAskMax: textToIntOrNull(d.salaryAskMax),
    currency: d.currency.trim() || null,
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
  onOpenSettings,
}: {
  config: AgentConfig;
  onChange: (c: AgentConfig) => void;
  /** Opens the Settings modal, optionally scrolled to a section. */
  onOpenSettings: (section: "job-search-policy") => void;
}) {
  const [drafts, setDrafts] = useState<ProfileDraft[]>(() => config.profiles.map(profileToDraft));
  // Read-only display of the legacy fallback window; its writer is Settings.
  const [cooldownDays, setCooldownDays] = useState(numberToText(config.cooldownDays));
  const [maxApplicationsPerRun, setMaxApplicationsPerRun] = useState(
    numberToText(config.maxApplicationsPerRun),
  );
  const [maxPostingAgeDays, setMaxPostingAgeDays] = useState(
    numberToText(config.maxPostingAgeDays),
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
      // Cooldown windows are NOT saved here: Settings' Job search policy
      // section is their single writer, so the two can never disagree.
      const fresh = await updateAgentConfig({
        profiles: drafts.map(draftToProfile),
        maxApplicationsPerRun: textToIntOrNull(maxApplicationsPerRun),
        maxPostingAgeDays: textToIntOrNull(maxPostingAgeDays),
      });
      onChange(fresh);
      setDrafts(fresh.profiles.map(profileToDraft));
      setCooldownDays(numberToText(fresh.cooldownDays));
      setMaxApplicationsPerRun(numberToText(fresh.maxApplicationsPerRun));
      setMaxPostingAgeDays(numberToText(fresh.maxPostingAgeDays));
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
      {/* Above the profile cards deliberately: this applies to every profile,
          and a keyword-heavy profile can run to hundreds of lines, which put
          it below a scroll long enough that it could not be found. */}
      <TextField
        label="Only postings from the last (days)"
        size="small"
        value={maxPostingAgeDays}
        onChange={(e) => setMaxPostingAgeDays(e.target.value)}
        slotProps={{ htmlInput: { inputMode: "numeric" } }}
        sx={{ maxWidth: 420 }}
        helperText="Applies to all profiles. Filters discovery and rejects older postings when screening. Leave blank for no age filter. Press Save profiles below to apply."
      />
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
          label="Cooldown (same role / same company)"
          size="small"
          value={`${numberToText(config.cooldownDaysSameRole)} / ${numberToText(
            config.cooldownDaysSameCompany,
          )}`}
          slotProps={{ input: { readOnly: true } }}
          helperText="Blank inherits Cooldown days, then 90; 0 disables. Changed in Settings."
        />
        {cooldownDays !== "" && (
          <TextField
            label="Cooldown days"
            size="small"
            value={cooldownDays}
            slotProps={{ input: { readOnly: true } }}
            helperText="Legacy fallback window — changed in Settings too."
          />
        )}
        <Button variant="text" onClick={() => onOpenSettings("job-search-policy")}>
          Edit in Settings
        </Button>
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

/**
 * Read-only canonical CV notice. The CV is registered out-of-band by
 * truth.answers.register_canonical_cv, not from this page. This section
 * simply surfaces what file (if any) the unattended agent will attach.
 */
function CanonicalCvSection({ answers }: { answers: ProfileAnswers }) {
  const downloadUrl = answers.canonicalCvAssetId
    ? `/api/download/${encodeURIComponent(answers.canonicalCvAssetId)}`
    : null;

  return (
    <Section
      title="CV"
      description="The canonical CV you uploaded is what the agent attaches to every automated application. It is not tailored per posting."
    >
      {downloadUrl ? (
        <Link href={downloadUrl} target="_blank" rel="noreferrer">
          {answers.canonicalCvAssetId}
        </Link>
      ) : (
        <Alert severity="warning">
          No CV is registered. The agent will skip applications rather than substitute another file.
        </Alert>
      )}
    </Section>
  );
}

/** The 20 ATS answers and cover-letter claim sources. Each has its own MUI
 * TextField and is sent on Save. Salary is absent; canonicalCvAssetId is never
 * sent from the form (the read-only CV section above surfaces it instead).
 * The agent uses these; the cover-letter writer sources facts from them. */
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


