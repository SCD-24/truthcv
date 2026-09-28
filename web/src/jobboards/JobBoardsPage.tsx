import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { Alert, Button, Divider, Paper, Stack, Typography } from "@mui/material";

import { getAgentConfig, getSigninQueue, updateAgentConfig } from "../api/client";
import type { AgentConfig, JobBoard, SigninQueueSite } from "../api/types";
import { browserSessionPath } from "../routes";
import { AddBoardControl } from "./AddBoardControl";
import { BoardRow } from "./BoardRow";
import { EditBoardDialog } from "./EditBoardDialog";
import { sourceKey } from "./sourceKey";

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

/** Job boards: one list, not two — every board the agent searches is also a
 * site you can sign in to. Default boards cannot be removed but can be
 * switched off; the "Needs attention" queue is the agent's own experience of
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
  const [editingBoard, setEditingBoard] = useState<JobBoard | null>(null);

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

  function handleModeChange(source: string, mode: string) {
    if (!config) return;
    persist(
      config.jobBoards.map((b) =>
        b.source === source
          ? { ...b, mode: mode as JobBoard["mode"], searchUrl: mode === "direct" ? b.searchUrl : "" }
          : b,
      ),
    );
  }

  function handleToggle(source: string, enabled: boolean) {
    // Ignore a toggle while a save is in flight: the PUT replaces the whole
    // board list, so a second toggle built from the same stale config would
    // silently undo the first.
    if (!config || saving) return;
    persist(config.jobBoards.map((b) => (b.source === source ? { ...b, enabled } : b)));
  }

  function handleEditSave(original: JobBoard, updated: JobBoard) {
    if (!config) return;
    setEditingBoard(null);
    persist(config.jobBoards.map((b) => (b.source === original.source ? updated : b)));
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
            A board marked API is pulled from directly using a key you save here; there is nothing to
            sign in to for those.
          </Typography>
        </Stack>
        {error && <Alert severity="error">{error}</Alert>}
        <NeedsAttention />
        <Divider />
        <Typography variant="subtitle2">Your job boards</Typography>
        {config.jobBoards.map((board) => (
          <BoardRow
            key={board.source}
            board={board}
            onRemove={() => handleRemove(board.source)}
            onModeChange={(mode) => handleModeChange(board.source, mode)}
            onEdit={() => setEditingBoard(board)}
            onToggleEnabled={(enabled) => handleToggle(board.source, enabled)}
          />
        ))}
        {editingBoard && (
          <EditBoardDialog
            board={editingBoard}
            existingSources={
              new Set(
                config.jobBoards
                  .filter((b) => b.source !== editingBoard.source)
                  .map((b) => sourceKey(b.source)),
              )
            }
            onClose={() => setEditingBoard(null)}
            onSave={(updated) => handleEditSave(editingBoard, updated)}
            saving={saving}
          />
        )}
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
