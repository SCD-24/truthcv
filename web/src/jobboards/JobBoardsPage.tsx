import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import {
  Alert,
  Button,
  Chip,
  Divider,
  MenuItem,
  Paper,
  Select,
  Stack,
  TextField,
  Tooltip,
  Typography,
} from "@mui/material";

import { getAgentConfig, getSigninQueue, updateAgentConfig } from "../api/client";
import type { AgentConfig, JobBoard, SigninQueueSite } from "../api/types";
import { browserSessionPath } from "../routes";

// Known board keys offered by the "add a board" control. This carries no
// sign-in URLs or domains — those are resolved server-side per board — it
// only lists the catalog keys a user can pick instead of typing a domain.
const KNOWN_BOARDS = ["ashby", "greenhouse", "lever", "personio", "linkedin", "workday"];

function hostLabel(iso: string): string {
  if (!iso) return "";
  const d = new Date(iso);
  return Number.isNaN(d.getTime())
    ? ""
    : d.toLocaleDateString(undefined, { day: "numeric", month: "short" });
}

function NeedsAttention() {
  const navigate = useNavigate();
  const [sites, setSites] = useState<SigninQueueSite[] | null>(null);
  const [error, setError] = useState("");

  useEffect(() => {
    let live = true;
    getSigninQueue()
      .then((q) => live && setSites(q.sites))
      .catch((e: Error) => live && setError(e.message));
    return () => {
      live = false;
    };
  }, []);

  return (
    <Stack spacing={2}>
      {error && <Alert severity="error">{error}</Alert>}
      <Typography variant="subtitle2">Needs attention</Typography>
      <Typography variant="body2" color="text.secondary">
        Sites the agent was actually blocked by — this may include sites not on your board list below.
      </Typography>
      {sites && sites.length === 0 && (
        <Typography variant="body2" color="text.secondary">
          No sites are waiting on a sign-in.
        </Typography>
      )}
      {sites?.map((site) => (
        <Stack
          key={site.host}
          direction="row"
          spacing={2}
          sx={{ alignItems: "center", justifyContent: "space-between" }}
        >
          <Stack spacing={0.25}>
            <Typography variant="body2">{site.host}</Typography>
            <Typography variant="caption" color="text.secondary">
              {site.waiting} {site.waiting === 1 ? "posting" : "postings"} waiting
              {site.companies.length > 0 && ` · ${site.companies.join(", ")}`}
              {hostLabel(site.lastBlockedAt) && ` · last blocked ${hostLabel(site.lastBlockedAt)}`}
            </Typography>
          </Stack>
          <Button variant="contained" size="small" onClick={() => navigate(browserSessionPath(site.signinUrl))}>
            Sign in to {site.host}
          </Button>
        </Stack>
      ))}
    </Stack>
  );
}

function BoardRow({ board, onRemove }: { board: JobBoard; onRemove: () => void }) {
  const navigate = useNavigate();
  const noSigninUrl = !board.effectiveSigninUrl;

  return (
    <Stack direction="row" spacing={2} sx={{ alignItems: "center", justifyContent: "space-between" }}>
      <Stack direction="row" spacing={1} sx={{ alignItems: "center" }}>
        <Typography variant="body2">{board.domain || board.source}</Typography>
        {board.isDefault && (
          <Tooltip title="Default boards are always searched and cannot be removed.">
            <Chip label="Default" size="small" />
          </Tooltip>
        )}
      </Stack>
      <Stack direction="row" spacing={1}>
        <Tooltip title={noSigninUrl ? "No sign-in URL is set for this board" : ""}>
          <span>
            <Button
              variant="outlined"
              size="small"
              disabled={noSigninUrl}
              onClick={() => navigate(browserSessionPath(board.effectiveSigninUrl))}
            >
              Sign in
            </Button>
          </span>
        </Tooltip>
        {!board.isDefault && (
          <Button size="small" color="error" onClick={onRemove}>
            Remove
          </Button>
        )}
      </Stack>
    </Stack>
  );
}

function AddBoardControl({ onAdd, existing }: { onAdd: (board: JobBoard) => void; existing: Set<string> }) {
  const [choice, setChoice] = useState("");
  const [customDomain, setCustomDomain] = useState("");
  const [customSigninUrl, setCustomSigninUrl] = useState("");

  function handleAdd() {
    if (choice === "__custom__") {
      if (!customDomain.trim()) return;
      onAdd({
        source: customDomain.trim(),
        signinUrl: customSigninUrl.trim(),
        domain: customDomain.trim(),
        effectiveSigninUrl: customSigninUrl.trim(),
        isDefault: false,
      });
      setCustomDomain("");
      setCustomSigninUrl("");
    } else if (choice) {
      onAdd({ source: choice, signinUrl: "", domain: "", effectiveSigninUrl: "", isDefault: false });
    }
    setChoice("");
  }

  return (
    <Stack spacing={1}>
      <Stack direction="row" spacing={1} sx={{ alignItems: "center" }}>
        <Select
          size="small"
          displayEmpty
          value={choice}
          onChange={(e) => setChoice(e.target.value)}
          sx={{ minWidth: 200 }}
        >
          <MenuItem value="">
            <em>Add a board…</em>
          </MenuItem>
          {KNOWN_BOARDS.filter((source) => !existing.has(source)).map((source) => (
            <MenuItem key={source} value={source}>
              {source}
            </MenuItem>
          ))}
          <MenuItem value="__custom__">Custom domain…</MenuItem>
        </Select>
        <Button size="small" variant="outlined" disabled={!choice} onClick={handleAdd}>
          Add
        </Button>
      </Stack>
      {choice === "__custom__" && (
        <Stack direction="row" spacing={1}>
          <TextField
            size="small"
            label="Domain"
            value={customDomain}
            onChange={(e) => setCustomDomain(e.target.value)}
          />
          <TextField
            size="small"
            label="Sign-in URL (optional)"
            value={customSigninUrl}
            onChange={(e) => setCustomSigninUrl(e.target.value)}
          />
        </Stack>
      )}
    </Stack>
  );
}

/** Job boards: one list, not two — every board the agent searches is also a
 * site you can sign in to. Default boards are always searched and cannot be
 * removed; the "Needs attention" queue is the agent's own experience of
 * being blocked, and it is deliberately the only sign-in status shown here —
 * TruthCV has no way to confirm a session is still valid, so claiming a
 * board is "signed in" would be an assertion nothing checks.
 *
 * Its own top-level page (moved out of Agents): loads its own config on
 * mount rather than receiving it as a prop, since nothing else on this page
 * depends on the rest of the agent's configuration. */
export function JobBoardsPage() {
  const [config, setConfig] = useState<AgentConfig | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let live = true;
    getAgentConfig()
      .then((c) => live && setConfig(c))
      .catch((e: unknown) =>
        live && setLoadError(e instanceof Error ? e.message : "Couldn't load the job boards."),
      );
    return () => {
      live = false;
    };
  }, []);

  async function persist(jobBoards: JobBoard[]) {
    setSaving(true);
    setError(null);
    try {
      const fresh = await updateAgentConfig({ jobBoards });
      setConfig(fresh);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Couldn't update job boards.");
    } finally {
      setSaving(false);
    }
  }

  function handleRemove(source: string) {
    if (!config) return;
    persist(config.jobBoards.filter((b) => b.source !== source));
  }

  function handleAdd(board: JobBoard) {
    if (!config) return;
    if (config.jobBoards.some((b) => b.source === board.source)) return;
    persist([...config.jobBoards, board]);
  }

  if (loadError) {
    return (
      <Paper variant="outlined" sx={{ p: 3 }}>
        <Alert severity="error">{loadError}</Alert>
      </Paper>
    );
  }

  if (!config) {
    return (
      <Paper variant="outlined" sx={{ p: 3 }}>
        <Typography variant="body2" color="text.secondary">
          Loading job boards…
        </Typography>
      </Paper>
    );
  }

  return (
    <Paper variant="outlined" sx={{ p: 3 }}>
      <Stack spacing={2}>
        <Stack spacing={0.5}>
          <Typography variant="h6">Job boards</Typography>
          <Typography variant="body2" color="text.secondary">
            These are the boards the agent searches AND the sites you sign in to — one list, not two.
          </Typography>
        </Stack>
        {error && <Alert severity="error">{error}</Alert>}
        <NeedsAttention />
        <Divider />
        <Typography variant="subtitle2">Your job boards</Typography>
        {config.jobBoards.map((board) => (
          <BoardRow key={board.source} board={board} onRemove={() => handleRemove(board.source)} />
        ))}
        <AddBoardControl
          onAdd={handleAdd}
          existing={new Set(config.jobBoards.map((b) => b.source.toLowerCase()))}
        />
        {saving && (
          <Typography variant="caption" color="text.secondary">
            Saving…
          </Typography>
        )}
      </Stack>
    </Paper>
  );
}
