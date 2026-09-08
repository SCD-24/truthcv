import { useState } from "react";
import Box from "@mui/material/Box";
import Paper from "@mui/material/Paper";
import Typography from "@mui/material/Typography";
import Chip from "@mui/material/Chip";
import Button from "@mui/material/Button";
import IconButton from "@mui/material/IconButton";
import Collapse from "@mui/material/Collapse";
import Dialog from "@mui/material/Dialog";
import DialogTitle from "@mui/material/DialogTitle";
import DialogContent from "@mui/material/DialogContent";
import DialogActions from "@mui/material/DialogActions";
import TextField from "@mui/material/TextField";
import EditOutlinedIcon from "@mui/icons-material/EditOutlined";
import DeleteOutlineIcon from "@mui/icons-material/DeleteOutlined";
import ExpandMoreIcon from "@mui/icons-material/ExpandMore";
import ExpandLessIcon from "@mui/icons-material/ExpandLess";
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

/** Human-readable message from a thrown value, preferring the server's own. */
function errText(e: unknown, fallback: string): string {
  return e instanceof Error ? e.message : fallback;
}

type DraftFragment = { id: string; slot: string; title: string; text: string };

/** Modal form for creating or editing a user fragment. Slot is always fixed
 * (a fragment can't move between slots after creation) and id is server
 * assigned, so both are shown read-only. */
function FragmentEditor({
  draft,
  onCancel,
  onSaved,
  onError,
}: {
  draft: DraftFragment;
  onCancel: () => void;
  onSaved: () => void;
  onError: (message: string | null) => void;
}) {
  const [title, setTitle] = useState(draft.title);
  const [text, setText] = useState(draft.text);
  const [saving, setSaving] = useState(false);

  const save = async () => {
    onError(null);
    setSaving(true);
    try {
      await savePromptFragment({
        id: draft.id,
        slot: draft.slot,
        title,
        text,
      });
      onSaved();
    } catch (e) {
      onError(errText(e, "Couldn't save the fragment."));
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

/** Fragment text display with pre-wrapped whitespace. */
function FragmentText({ text }: { text: string }) {
  return (
    <Typography variant="body2" color="text.secondary" sx={{ whiteSpace: "pre-wrap" }}>
      {text}
    </Typography>
  );
}

/** One fragment row: title, slot badge, seeded badge, recommended chip (if applicable),
 * expand button to reveal text, and — for user fragments only — edit/delete controls. */
function FragmentRow({
  fragment,
  onEdit,
  onDeleted,
  onError,
}: {
  fragment: PromptFragment;
  onEdit: () => void;
  onDeleted: () => void;
  onError: (message: string | null) => void;
}) {
  const [open, setOpen] = useState(false);

  return (
    <Box component="li" sx={{ listStyle: "none" }}>
      <Box sx={{ display: "flex", alignItems: "center", gap: 1, py: 0.5 }}>
        <IconButton
          size="small"
          onClick={() => setOpen(!open)}
          aria-expanded={open}
          aria-label={`Show text for ${fragment.title}`}
          sx={{ ml: -1 }}
        >
          {open ? <ExpandLessIcon fontSize="small" /> : <ExpandMoreIcon fontSize="small" />}
        </IconButton>
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
        {fragment.recommended && (
          <Chip
            size="small"
            label="Recommended"
            color="primary"
            variant="outlined"
            aria-label={`${fragment.title} is recommended; presets should include it`}
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
              onClick={async () => {
                onError(null);
                try {
                  await deletePromptFragment(fragment.id);
                  onDeleted();
                } catch (e) {
                  onError(errText(e, "Couldn't delete the fragment."));
                }
              }}
            >
              <DeleteOutlineIcon fontSize="small" />
            </IconButton>
          </>
        )}
      </Box>
      <Collapse in={open} timeout="auto" unmountOnExit>
        <Box sx={{ pl: 4, pr: 2, pb: 1 }}>
          <FragmentText text={fragment.text} />
        </Box>
      </Collapse>
    </Box>
  );
}

/** One slot group: its label, the fragments in it, and an "add" button that
 * opens the editor pre-filled to that slot. */
function SlotGroup({
  slot,
  fragments,
  onChange,
  onError,
}: {
  slot: string;
  fragments: PromptFragment[];
  onChange: () => void;
  onError: (message: string | null) => void;
}) {
  const [draft, setDraft] = useState<DraftFragment | null>(null);
  const rows = fragmentsInSlot(fragments, slot);

  const startCreate = () => setDraft({ id: "", slot, title: "", text: "" });
  const startEdit = (f: PromptFragment) =>
    setDraft({ id: f.id, slot: f.slot, title: f.title, text: f.text });

  return (
    <Paper component="section" aria-labelledby={`slot-${slot}-label`} sx={{ p: 2, mb: 2 }}>
      <Typography id={`slot-${slot}-label`} variant="subtitle1" component="h3" sx={{ textTransform: "capitalize" }}>
        {slot}
      </Typography>
      <Box component="ul" sx={{ p: 0, m: 0 }}>
        {rows.map((f) => (
          <FragmentRow
            key={f.id}
            fragment={f}
            onEdit={() => startEdit(f)}
            onDeleted={onChange}
            onError={onError}
          />
        ))}
      </Box>
      <Button size="small" startIcon={<AddIcon fontSize="small" />} onClick={startCreate}>
        Add fragment
      </Button>
      {draft && (
        <FragmentEditor
          draft={draft}
          onError={onError}
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
  onError,
}: {
  fragments: PromptFragment[];
  onChange: () => void;
  onError: (message: string | null) => void;
}) {
  return (
    <Box component="section" aria-label="Prompt fragments">
      <Typography variant="h6" component="h2" sx={{ mb: 1 }}>
        Fragments
      </Typography>
      {SLOTS.map((slot) => (
        <SlotGroup
          key={slot}
          slot={slot}
          fragments={fragments}
          onChange={onChange}
          onError={onError}
        />
      ))}
    </Box>
  );
}
