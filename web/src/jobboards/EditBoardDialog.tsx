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
 * dork-only board never uses it). The posting-link pattern is also shown
 * only in "direct" mode but, unlike the search URL, is editable even for
 * default/catalog boards since it only affects link recognition. A source
 * rename is refused client-side
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
  const [postingUrlPattern, setPostingUrlPattern] = useState(board.postingUrlPattern);
  const [collisionError, setCollisionError] = useState("");
  const [patternError, setPatternError] = useState("");

  useEffect(() => {
    setSource(board.source);
    setSigninUrl(board.signinUrl);
    setSearchUrl(board.searchUrl);
    setPostingUrlPattern(board.postingUrlPattern);
    setCollisionError("");
    setPatternError("");
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
    // Only direct boards expose the field; any other mode keeps its stored
    // value untouched rather than silently clearing it on an unrelated edit.
    const isDirect = board.mode === "direct";
    const trimmedPattern = isDirect ? postingUrlPattern.trim() : board.postingUrlPattern;
    if (isDirect && trimmedPattern && !/^https?:\/\//.test(trimmedPattern)) {
      setPatternError("Must start with http:// or https://");
      return;
    }
    setCollisionError("");
    setPatternError("");
    onSave({
      ...board,
      source: board.isDefault ? board.source : trimmedSource,
      signinUrl: signinUrl.trim(),
      searchUrl: board.isDefault
        ? board.searchUrl
        : board.mode === "direct"
          ? searchUrl.trim()
          : "",
      postingUrlPattern: trimmedPattern,
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
          {board.mode === "direct" && (
            <TextField
              label="Posting link pattern (optional)"
              size="small"
              value={postingUrlPattern}
              onChange={(e) => setPostingUrlPattern(e.target.value)}
              error={!!patternError}
              helperText={patternError || "e.g. https://www.example.com/jobs/*"}
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
