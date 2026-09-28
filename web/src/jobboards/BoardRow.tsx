import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { Alert, Button, Chip, MenuItem, Select, Stack, TextField, Tooltip, Typography } from "@mui/material";

import { getJobBoardKey, saveJobBoardKey, testJobBoardKey } from "../api/client";
import type { JobBoard, JobBoardKeyStatus } from "../api/types";
import { browserSessionPath } from "../routes";
import { boardLabel } from "./boardLabels";

/** The credential control for an API-backed board: a write-only API key field
 * where every other board gets a "Sign in" button. The key is never read back
 * from the server — the status only says whether one is saved — so the field
 * always starts blank and submitting a blank one clears the stored key. */
function ApiKeyControl({ source }: { source: string }) {
  const [status, setStatus] = useState<JobBoardKeyStatus | null>(null);
  const [value, setValue] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");

  useEffect(() => {
    let live = true;
    getJobBoardKey(source)
      .then((s) => live && setStatus(s))
      .catch((e: Error) => live && setError(e.message));
    return () => {
      live = false;
    };
  }, [source]);

  async function handleSave() {
    setBusy(true);
    setError("");
    setNotice("");
    try {
      setStatus(await saveJobBoardKey(source, value));
      setValue("");
      setNotice("Saved.");
    } catch (e) {
      setError(e instanceof Error ? e.message : "Couldn't save the API key.");
    } finally {
      setBusy(false);
    }
  }

  async function handleTest() {
    setBusy(true);
    setError("");
    setNotice("");
    try {
      const result = await testJobBoardKey(source);
      if (result.ok) setNotice(result.detail);
      else setError(result.detail);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Couldn't reach the board.");
    } finally {
      setBusy(false);
    }
  }

  const encryptionOff = status !== null && !status.encryptionAvailable;

  return (
    <Stack spacing={1} sx={{ pl: 2 }}>
      {encryptionOff && (
        <Alert severity="warning">Set ENCRYPTION_KEY in .env before saving an API key.</Alert>
      )}
      {error && <Alert severity="error">{error}</Alert>}
      {notice && <Alert severity="success">{notice}</Alert>}
      <Typography variant="caption" color="text.secondary">
        {status?.keySet
          ? "An API key is saved. Enter a new one to replace it, or save an empty field to remove it."
          : "This board is pulled from over its API — save an API key instead of signing in. Generate one under Advanced · API access on Remote Rocketship (an active subscription is required)."}
      </Typography>
      <Stack direction="row" spacing={1} sx={{ alignItems: "center" }}>
        <TextField
          size="small"
          type="password"
          label="API key"
          autoComplete="off"
          value={value}
          disabled={busy || encryptionOff}
          onChange={(e) => setValue(e.target.value)}
          sx={{ minWidth: 260 }}
        />
        <Button size="small" variant="contained" disabled={busy || encryptionOff} onClick={handleSave}>
          Save key
        </Button>
        <Button size="small" variant="outlined" disabled={busy || !status?.keySet} onClick={handleTest}>
          Test
        </Button>
      </Stack>
    </Stack>
  );
}

/** How postings are found on this board — a fixed label for a catalog board
 * (its mode can't be changed), or a live selector for a custom one. A locked
 * board is ALWAYS rendered as plain text, never a disabled control, so it
 * cannot be mistaken for something the operator could enable. */
function BoardModeControl({ board, onModeChange }: { board: JobBoard; onModeChange: (mode: string) => void }) {
  if (board.modeLocked) {
    return (
      <Typography variant="caption" color="text.secondary">
        {board.isApi
          ? board.keyRequired
            ? "Postings come from this board's own API — only the API key below is configurable."
            : "Postings come from this board's own public API — nothing to configure."
          : "Searched via Google."}
      </Typography>
    );
  }
  return (
    <Select
      size="small"
      value={board.mode || "dork"}
      onChange={(e) => onModeChange(e.target.value)}
      sx={{ minWidth: 220 }}
      inputProps={{ "aria-label": "Mode" }}
    >
      <MenuItem value="dork">Google dork</MenuItem>
      <MenuItem value="direct">Search the site directly</MenuItem>
    </Select>
  );
}

export function BoardRow({
  board,
  onRemove,
  onModeChange,
  onEdit,
}: {
  board: JobBoard;
  onRemove: () => void;
  onModeChange: (mode: string) => void;
  onEdit: () => void;
}) {
  const navigate = useNavigate();
  const noSigninUrl = !board.effectiveSigninUrl;

  return (
    <Stack spacing={1}>
      <Stack direction="row" spacing={2} sx={{ alignItems: "center", justifyContent: "space-between" }}>
        <Stack direction="row" spacing={1} sx={{ alignItems: "center" }}>
          <Typography variant="body2">{boardLabel(board)}</Typography>
          {board.isDefault && (
            <Tooltip title="Default boards are always searched and cannot be removed.">
              <Chip label="Default" size="small" />
            </Tooltip>
          )}
          {board.isApi && (
            <Tooltip
              title={
                board.keyRequired
                  ? "Pulled from over its API with a saved key — there is nothing to sign in to."
                  : "Pulled from over its own public API — there is nothing to sign in to."
              }
            >
              <Chip label="API" size="small" variant="outlined" />
            </Tooltip>
          )}
        </Stack>
        <Stack direction="row" spacing={1} sx={{ alignItems: "center" }}>
          <BoardModeControl board={board} onModeChange={onModeChange} />
          {!board.isApi && (
            <Button variant="outlined" size="small" onClick={onEdit}>
              Edit
            </Button>
          )}
          {!board.isApi && (
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
          )}
          {!board.isDefault && (
            <Button size="small" color="error" onClick={onRemove}>
              Remove
            </Button>
          )}
        </Stack>
      </Stack>
      {board.isApi && board.keyRequired && <ApiKeyControl source={board.source} />}
    </Stack>
  );
}
