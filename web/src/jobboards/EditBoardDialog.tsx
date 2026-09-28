import { useEffect, useState } from "react";
import {
  Alert,
  Button,
  Dialog,
  DialogActions,
  DialogContent,
  DialogTitle,
  Stack,
  TextField,
} from "@mui/material";

import type { JobBoard } from "../api/types";
import { sourceKey } from "./sourceKey";

/** Edit dialog for a single job board. Default (catalog) boards only allow a
 * sign-in URL override; custom boards can also have their source renamed and
 * their search URL template edited (shown only in "direct" mode, since a
 * dork-only board never uses it). A source rename is refused client-side
 * when it collides, casefolded and trimmed, with another board already on
 * the list — the server still enforces the rest of the searchUrl rules and
 * any 422 it returns is surfaced by the caller's own error Alert. */
export function EditBoardDialog({
  board,
  existingSources,
  onClose,
  onSave,
  saving,
}: {
  board: JobBoard;
  existingSources: Set<string>;
  onClose: () => void;
  onSave: (updated: JobBoard) => void;
  saving: boolean;
}) {
  const [source, setSource] = useState(board.source);
  const [signinUrl, setSigninUrl] = useState(board.signinUrl);
  const [searchUrl, setSearchUrl] = useState(board.searchUrl);
  const [collisionError, setCollisionError] = useState("");

  useEffect(() => {
    setSource(board.source);
    setSigninUrl(board.signinUrl);
    setSearchUrl(board.searchUrl);
    setCollisionError("");
  }, [board]);

  function handleSave() {
    const trimmedSource = source.trim();
    if (!board.isDefault) {
      const key = sourceKey(trimmedSource);
      if (!trimmedSource || existingSources.has(key)) {
        setCollisionError("Another board already uses this source.");
        return;
      }
    }
    setCollisionError("");
    onSave({
      ...board,
      source: board.isDefault ? board.source : trimmedSource,
      signinUrl: signinUrl.trim(),
      searchUrl: board.isDefault
        ? board.searchUrl
        : board.mode === "direct"
          ? searchUrl.trim()
          : "",
    });
  }

  return (
    <Dialog open onClose={onClose} fullWidth maxWidth="sm">
      <DialogTitle>Edit board</DialogTitle>
      <DialogContent>
        <Stack spacing={2} sx={{ mt: 1 }}>
          {collisionError && <Alert severity="error">{collisionError}</Alert>}
          {!board.isDefault && (
            <TextField
              label="Source"
              size="small"
              value={source}
              onChange={(e) => setSource(e.target.value)}
              autoFocus
            />
          )}
          <TextField
            label="Sign-in URL"
            size="small"
            value={signinUrl}
            onChange={(e) => setSigninUrl(e.target.value)}
            autoFocus={board.isDefault}
          />
          {!board.isDefault && board.mode === "direct" && (
            <TextField
              label="Search URL template"
              size="small"
              value={searchUrl}
              onChange={(e) => setSearchUrl(e.target.value)}
              helperText="e.g. https://www.adzuna.de/search?q={keywords}&loc={location} — {keywords} required, {location} optional"
            />
          )}
        </Stack>
      </DialogContent>
      <DialogActions>
        <Button onClick={onClose}>Cancel</Button>
        <Button variant="contained" disabled={saving} onClick={handleSave}>
          Save
        </Button>
      </DialogActions>
    </Dialog>
  );
}
