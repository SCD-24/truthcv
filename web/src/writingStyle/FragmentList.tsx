import { useState } from "react";
import Box from "@mui/material/Box";
import Paper from "@mui/material/Paper";
import Typography from "@mui/material/Typography";
import Chip from "@mui/material/Chip";
import Button from "@mui/material/Button";
import IconButton from "@mui/material/IconButton";
import Dialog from "@mui/material/Dialog";
import DialogTitle from "@mui/material/DialogTitle";
import DialogContent from "@mui/material/DialogContent";
import DialogActions from "@mui/material/DialogActions";
import TextField from "@mui/material/TextField";
import EditOutlinedIcon from "@mui/icons-material/EditOutlined";
import DeleteOutlineIcon from "@mui/icons-material/DeleteOutlined";
import AddIcon from "@mui/icons-material/Add";
import LockOutlinedIcon from "@mui/icons-material/LockOutlined";
import type { PromptFragment } from "../api/client";
import { deletePromptFragment, savePromptFragment } from "../api/client";

/** Fixed display order for the four fragment slots. */
export const SLOTS = ["voice", "structure", "opener", "rules"] as const;

/** Fragments belonging to one slot, in the order the caller passed them. */
function fragmentsInSlot(fragments: PromptFragment[], slot: string): PromptFragment[] {
  return fragments.filter((f) => f.slot === slot);
}

/** Parses the comma-separated "conflicts with" field back into an id list. */
function parseConflicts(text: string): string[] {
  return text
    .split(",")
    .map((s) => s.trim())
    .filter((s) => s.length > 0);
}

type DraftFragment = { id: string; slot: string; title: string; text: string; conflictsWith: string };

/** Modal form for creating or editing a user fragment. Slot is always fixed
 * (a fragment can't move between slots after creation) and id is server
 * assigned, so both are shown read-only. */
function FragmentEditor({
  draft,
  onCancel,
  onSaved,
}: {
  draft: DraftFragment;
  onCancel: () => void;
  onSaved: () => void;
}) {
  const [title, setTitle] = useState(draft.title);
  const [text, setText] = useState(draft.text);
  const [conflicts, setConflicts] = useState(draft.conflictsWith);
  const [saving, setSaving] = useState(false);

  const save = async () => {
    setSaving(true);
    try {
      await savePromptFragment({
        id: draft.id,
        slot: draft.slot,
        title,
        text,
        conflictsWith: parseConflicts(conflicts),
      });
      onSaved();
    } finally {
      setSaving(false);
    }
  };

  return (
    <Dialog open onClose={onCancel} onKeyDown={(e) => e.key === "Escape" && onCancel()}>
      <DialogTitle>{draft.id ? "Edit fragment" : "New fragment"}</DialogTitle>
      <DialogContent sx={{ display: "flex", flexDirection: "column", gap: 2, minWidth: 360 }}>
        <TextField label="Id" value={draft.id || "(assigned on save)"} disabled fullWidth />
        <TextField label="Slot" value={draft.slot} disabled fullWidth />
        <TextField
          label="Title"
          value={title}
          onChange={(e) => setTitle(e.target.value)}
          autoFocus
          fullWidth
        />
        <TextField
          label="Text"
          value={text}
          onChange={(e) => setText(e.target.value)}
          multiline
          minRows={3}
          fullWidth
        />
        <TextField
          label="Conflicts with (comma-separated fragment ids)"
          value={conflicts}
          onChange={(e) => setConflicts(e.target.value)}
          fullWidth
        />
      </DialogContent>
      <DialogActions>
        <Button onClick={onCancel}>Cancel</Button>
        <Button variant="contained" disabled={saving || !title.trim()} onClick={save}>
          Save
        </Button>
      </DialogActions>
    </Dialog>
  );
}

/** One fragment row: title, slot badge, seeded badge, and — for user
 * fragments only — edit/delete controls. */
function FragmentRow({
  fragment,
  onEdit,
  onDeleted,
}: {
  fragment: PromptFragment;
  onEdit: () => void;
  onDeleted: () => void;
}) {
  return (
    <Box
      component="li"
      sx={{ display: "flex", alignItems: "center", gap: 1, py: 0.5, listStyle: "none" }}
    >
      <Typography component="span" sx={{ flexGrow: 1 }}>
        {fragment.title}
      </Typography>
      {fragment.seeded && (
        <Chip
          size="small"
          icon={<LockOutlinedIcon fontSize="small" aria-hidden="true" />}
          label="Seeded"
          aria-label={`${fragment.title} is a seeded, read-only fragment`}
        />
      )}
      {!fragment.seeded && (
        <>
          <IconButton
            size="small"
            aria-label={`Edit ${fragment.title}`}
            onClick={onEdit}
          >
            <EditOutlinedIcon fontSize="small" />
          </IconButton>
          <IconButton
            size="small"
            aria-label={`Delete ${fragment.title}`}
            onClick={() => deletePromptFragment(fragment.id).then(onDeleted)}
          >
            <DeleteOutlineIcon fontSize="small" />
          </IconButton>
        </>
      )}
    </Box>
  );
}

/** One slot group: its label, the fragments in it, and an "add" button that
 * opens the editor pre-filled to that slot. */
function SlotGroup({
  slot,
  fragments,
  onChange,
}: {
  slot: string;
  fragments: PromptFragment[];
  onChange: () => void;
}) {
  const [draft, setDraft] = useState<DraftFragment | null>(null);
  const rows = fragmentsInSlot(fragments, slot);

  const startCreate = () =>
    setDraft({ id: "", slot, title: "", text: "", conflictsWith: "" });
  const startEdit = (f: PromptFragment) =>
    setDraft({ id: f.id, slot: f.slot, title: f.title, text: f.text, conflictsWith: f.conflictsWith.join(", ") });

  return (
    <Paper component="section" aria-labelledby={`slot-${slot}-label`} sx={{ p: 2, mb: 2 }}>
      <Typography id={`slot-${slot}-label`} variant="subtitle1" component="h3" sx={{ textTransform: "capitalize" }}>
        {slot}
      </Typography>
      <Box component="ul" sx={{ p: 0, m: 0 }}>
        {rows.map((f) => (
          <FragmentRow key={f.id} fragment={f} onEdit={() => startEdit(f)} onDeleted={onChange} />
        ))}
      </Box>
      <Button size="small" startIcon={<AddIcon fontSize="small" />} onClick={startCreate}>
        Add fragment
      </Button>
      {draft && (
        <FragmentEditor
          draft={draft}
          onCancel={() => setDraft(null)}
          onSaved={() => {
            setDraft(null);
            onChange();
          }}
        />
      )}
    </Paper>
  );
}

/** Left panel: fragments grouped by slot, with per-slot add and per-fragment
 * edit/delete for user fragments. Seeded fragments are read-only. */
export function FragmentList({
  fragments,
  onChange,
}: {
  fragments: PromptFragment[];
  onChange: () => void;
}) {
  return (
    <Box component="section" aria-label="Prompt fragments">
      <Typography variant="h6" component="h2" sx={{ mb: 1 }}>
        Fragments
      </Typography>
      {SLOTS.map((slot) => (
        <SlotGroup key={slot} slot={slot} fragments={fragments} onChange={onChange} />
      ))}
    </Box>
  );
}
