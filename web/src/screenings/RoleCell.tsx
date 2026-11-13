import { useState } from "react";
import type { KeyboardEvent } from "react";
import Stack from "@mui/material/Stack";
import Typography from "@mui/material/Typography";
import TableCell from "@mui/material/TableCell";
import TextField from "@mui/material/TextField";
import type { ScreeningLedgerItem } from "../api/types";

/** A role a user typed vs the role as last committed — if they match, a
 * commit is a no-op that must not fire a request. */
export function roleUnchanged(draft: string, stored: string): boolean {
  return draft === stored;
}

/** The edit state of one role: whether the field is open, its draft text and
 * the last save error, with `reset` to reseed from the stored role. */
function useRoleDraft(role: string) {
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState(role);
  const [error, setError] = useState("");

  const reset = (next: boolean) => {
    setDraft(role);
    setError("");
    setEditing(next);
  };

  return { editing, setEditing, draft, setDraft, error, setError, reset };
}

/** Commit/cancel/start handlers over the role draft; a commit saves via `onSave`. */
function useRoleEdit(record: ScreeningLedgerItem, onSave: (id: string, role: string) => Promise<void>) {
  const d = useRoleDraft(record.role);

  async function commit() {
    if (!d.editing) return;
    if (roleUnchanged(d.draft, record.role)) {
      d.setEditing(false);
      return;
    }
    d.setError("");
    try {
      await onSave(record.id, d.draft);
      d.setEditing(false);
    } catch (e) {
      d.setError(e instanceof Error ? e.message : "Couldn't save the role.");
    }
  }

  return { ...d, startEdit: () => d.reset(true), cancel: () => d.reset(false), commit };
}

type RoleEdit = ReturnType<typeof useRoleEdit>;

/** The inline error line under the role field, or nothing. */
function RoleError({ error }: { error: string }) {
  return error ? (
    <Typography variant="caption" color="error">
      {error}
    </Typography>
  ) : null;
}

/** The open role field: seeded with the draft, Enter commits, Escape cancels. */
function RoleEditor({ edit, busy }: { edit: RoleEdit; busy: boolean }) {
  const onKeyDown = (e: KeyboardEvent<HTMLInputElement>) => {
    if (e.key === "Enter") edit.commit();
    else if (e.key === "Escape") edit.cancel();
  };
  return (
    <TableCell>
      <Stack spacing={0.5}>
        <TextField
          size="small"
          autoFocus
          value={edit.draft}
          disabled={busy}
          onChange={(e) => edit.setDraft(e.target.value)}
          onKeyDown={onKeyDown}
          onBlur={edit.commit}
        />
        <RoleError error={edit.error} />
      </Stack>
    </TableCell>
  );
}

/** The Role cell, editable in place: click to open a text field seeded with
 * the current role, commit on Enter or blur, cancel on Escape. The server's
 * (possibly normalized) response is what gets shown — never the typed
 * string — and a rejected commit stays in edit mode with the server's
 * message, leaving the stored role untouched. */
export function RoleCell({
  record,
  busy,
  onSave,
}: {
  record: ScreeningLedgerItem;
  busy: boolean;
  onSave: (id: string, role: string) => Promise<void>;
}) {
  const edit = useRoleEdit(record, onSave);
  if (!edit.editing) {
    return (
      <TableCell onClick={edit.startEdit} sx={{ cursor: "pointer" }}>
        {record.role || "—"}
      </TableCell>
    );
  }
  return <RoleEditor edit={edit} busy={busy} />;
}
