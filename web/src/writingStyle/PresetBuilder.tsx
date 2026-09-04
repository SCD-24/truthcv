import { useEffect, useState } from "react";
import Box from "@mui/material/Box";
import Paper from "@mui/material/Paper";
import Typography from "@mui/material/Typography";
import Button from "@mui/material/Button";
import Checkbox from "@mui/material/Checkbox";
import FormControlLabel from "@mui/material/FormControlLabel";
import TextField from "@mui/material/TextField";
import MenuItem from "@mui/material/MenuItem";
import Alert from "@mui/material/Alert";
import { SLOTS } from "./FragmentList";
import type { PromptConflict, PromptFragment, PromptPreset } from "../api/client";
import { savePromptPreset, setDefaultPromptPreset, validatePromptPreset } from "../api/client";

const NEW_PRESET = "__new__";

/** Alert for missing recommended fragments. */
function MissingRecommendedAlert({
  fragments,
  fragmentIds,
}: {
  fragments: PromptFragment[];
  fragmentIds: string[];
}) {
  const missingRecommended = fragments.filter((f) => f.recommended && !fragmentIds.includes(f.id));
  if (missingRecommended.length === 0) return null;
  const titles = missingRecommended.map((f) => f.title).join(", ");
  return (
    <Alert severity="info" sx={{ mb: 2 }}>
      Recommended fragments not selected: {titles}. Letters may lose formatting or quality guardrails without them.
    </Alert>
  );
}

/** Messages for the fragments a conflict names, keyed by fragment id, so
 * each offending checkbox can show its own inline reason. */
function conflictsByFragment(conflicts: PromptConflict[]): Map<string, string[]> {
  const map = new Map<string, string[]>();
  for (const c of conflicts) {
    for (const id of c.fragmentIds) {
      map.set(id, [...(map.get(id) ?? []), c.message]);
    }
  }
  return map;
}

/** Loads the given preset's fields into local state, or clears them for
 * "New preset". */
function useSelectedPreset(presets: PromptPreset[], selectedId: string) {
  const [name, setName] = useState("");
  const [fragmentIds, setFragmentIds] = useState<string[]>([]);

  useEffect(() => {
    const preset = presets.find((p) => p.id === selectedId);
    setName(preset ? preset.name : "");
    setFragmentIds(preset ? preset.fragmentIds : []);
  }, [selectedId, presets]);

  return { name, setName, fragmentIds, setFragmentIds };
}

/** Right panel: pick or start a preset, toggle its fragments, see conflicts
 * live, and save. Conflicts are re-checked against the server on every
 * toggle so "Save" can never submit a preset the backend would reject. */
export function PresetBuilder({
  fragments,
  presets,
  onPresetsChange,
}: {
  fragments: PromptFragment[];
  presets: PromptPreset[];
  onPresetsChange: () => void;
}) {
  const [selectedId, setSelectedId] = useState<string>(NEW_PRESET);
  const { name, setName, fragmentIds, setFragmentIds } = useSelectedPreset(presets, selectedId);
  const [conflicts, setConflicts] = useState<PromptConflict[]>([]);
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    validatePromptPreset(fragmentIds).then(setConflicts);
  }, [fragmentIds]);

  const selectedPreset = presets.find((p) => p.id === selectedId) ?? null;
  const reasonsByFragment = conflictsByFragment(conflicts);

  const toggle = (id: string) => {
    setFragmentIds((prev) => (prev.includes(id) ? prev.filter((x) => x !== id) : [...prev, id]));
  };

  const save = async () => {
    setSaving(true);
    try {
      const saved = await savePromptPreset({
        id: selectedId === NEW_PRESET ? "" : selectedId,
        name,
        fragmentIds,
        isDefault: selectedPreset?.isDefault ?? false,
      });
      onPresetsChange();
      setSelectedId(saved.id);
    } finally {
      setSaving(false);
    }
  };

  const makeDefault = async () => {
    if (selectedId === NEW_PRESET) return;
    await setDefaultPromptPreset(selectedId);
    onPresetsChange();
  };

  return (
    <Box component="section" aria-label="Preset builder">
      <Typography variant="h6" component="h2" sx={{ mb: 1 }}>
        Presets
      </Typography>
      <TextField
        select
        label="Select a preset"
        value={selectedId}
        onChange={(e) => setSelectedId(e.target.value)}
        fullWidth
        sx={{ mb: 2 }}
      >
        <MenuItem value={NEW_PRESET}>New preset</MenuItem>
        {presets.map((p) => (
          <MenuItem key={p.id} value={p.id}>
            {p.name}
            {p.isDefault ? " (default)" : ""}
          </MenuItem>
        ))}
      </TextField>

      <TextField
        label="Preset name"
        value={name}
        onChange={(e) => setName(e.target.value)}
        fullWidth
        sx={{ mb: 2 }}
      />

      <Box role="status" aria-live="polite" aria-atomic="true">
        {conflicts.length > 0 && (
          <Alert severity="warning" sx={{ mb: 2 }}>
            {conflicts.map((c, i) => (
              <div key={i}>{c.message}</div>
            ))}
          </Alert>
        )}
        <MissingRecommendedAlert fragments={fragments} fragmentIds={fragmentIds} />
      </Box>

      {SLOTS.map((slot) => (
        <PresetSlotGroup
          key={slot}
          slot={slot}
          fragments={fragments}
          fragmentIds={fragmentIds}
          reasonsByFragment={reasonsByFragment}
          onToggle={toggle}
        />
      ))}

      <Box sx={{ display: "flex", gap: 2, mt: 2 }}>
        <Button
          variant="contained"
          disabled={saving || conflicts.length > 0 || !name.trim()}
          onClick={save}
        >
          Save preset
        </Button>
        <Button
          variant="outlined"
          disabled={selectedId === NEW_PRESET || !!selectedPreset?.seeded}
          onClick={makeDefault}
        >
          Set as default
        </Button>
      </Box>
    </Box>
  );
}

/** One slot's checkboxes in the preset builder, each with its own inline
 * conflict reason (if any) right next to it. */
function PresetSlotGroup({
  slot,
  fragments,
  fragmentIds,
  reasonsByFragment,
  onToggle,
}: {
  slot: string;
  fragments: PromptFragment[];
  fragmentIds: string[];
  reasonsByFragment: Map<string, string[]>;
  onToggle: (id: string) => void;
}) {
  const rows = fragments.filter((f) => f.slot === slot);
  if (rows.length === 0) return null;
  return (
    <Paper component="fieldset" sx={{ p: 2, mb: 2, border: "1px solid", borderColor: "divider" }}>
      <Typography component="legend" variant="subtitle2" sx={{ textTransform: "capitalize" }}>
        {slot}
      </Typography>
      {rows.map((f) => {
        const reasons = reasonsByFragment.get(f.id);
        return (
          <Box key={f.id}>
            <Box sx={{ display: "flex", alignItems: "center", gap: 1 }}>
              <FormControlLabel
                control={
                  <Checkbox
                    checked={fragmentIds.includes(f.id)}
                    onChange={() => onToggle(f.id)}
                  />
                }
                label={f.title}
              />
              {f.recommended && (
                <Typography variant="caption" color="text.secondary">
                  Recommended
                </Typography>
              )}
            </Box>
            {reasons && (
              <Typography
                component="span"
                variant="caption"
                sx={{ color: "error.main", ml: 1 }}
              >
                {reasons.join("; ")}
              </Typography>
            )}
          </Box>
        );
      })}
    </Paper>
  );
}
