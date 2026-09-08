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
import type { PromptFragment, PromptPreset } from "../api/client";
import { savePromptPreset, setDefaultPromptPreset } from "../api/client";

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

/** Human-readable message from a thrown value, preferring the server's own. */
function errText(e: unknown, fallback: string): string {
  return e instanceof Error ? e.message : fallback;
}

/** Right panel: pick or start a preset, toggle any combination of its
 * fragments, and save. Slots group fragments for display only — a preset may
 * hold several fragments from the same slot, and nothing checks them against
 * one another. */
export function PresetBuilder({
  fragments,
  presets,
  onPresetsChange,
  onError,
}: {
  fragments: PromptFragment[];
  presets: PromptPreset[];
  onPresetsChange: () => void;
  onError: (message: string | null) => void;
}) {
  const [selectedId, setSelectedId] = useState<string>(NEW_PRESET);
  const { name, setName, fragmentIds, setFragmentIds } = useSelectedPreset(presets, selectedId);
  const [saving, setSaving] = useState(false);

  const selectedPreset = presets.find((p) => p.id === selectedId) ?? null;

  const toggle = (id: string) => {
    setFragmentIds((prev) => (prev.includes(id) ? prev.filter((x) => x !== id) : [...prev, id]));
  };

  const save = async () => {
    onError(null);
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
    } catch (e) {
      onError(errText(e, "Couldn't save the preset."));
    } finally {
      setSaving(false);
    }
  };

  const makeDefault = async () => {
    if (selectedId === NEW_PRESET) return;
    onError(null);
    try {
      await setDefaultPromptPreset(selectedId);
      onPresetsChange();
    } catch (e) {
      onError(errText(e, "Couldn't set the default preset."));
    }
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
        <MissingRecommendedAlert fragments={fragments} fragmentIds={fragmentIds} />
      </Box>

      {SLOTS.map((slot) => (
        <PresetSlotGroup
          key={slot}
          slot={slot}
          fragments={fragments}
          fragmentIds={fragmentIds}
          onToggle={toggle}
        />
      ))}

      <Box sx={{ display: "flex", gap: 2, mt: 2 }}>
        <Button
          variant="contained"
          disabled={saving || !name.trim() || !!selectedPreset?.seeded}
          onClick={save}
        >
          Save preset
        </Button>
        <Button
          variant="outlined"
          disabled={selectedId === NEW_PRESET}
          onClick={makeDefault}
        >
          Set as default
        </Button>
      </Box>
      {selectedPreset?.seeded && (
        <Typography variant="caption" color="text.secondary" sx={{ display: "block", mt: 1 }}>
          Shipped presets can't be edited. Pick "New preset" to build your own.
        </Typography>
      )}
    </Box>
  );
}

/** One slot's checkboxes in the preset builder. Any number may be ticked. */
function PresetSlotGroup({
  slot,
  fragments,
  fragmentIds,
  onToggle,
}: {
  slot: string;
  fragments: PromptFragment[];
  fragmentIds: string[];
  onToggle: (id: string) => void;
}) {
  const rows = fragments.filter((f) => f.slot === slot);
  if (rows.length === 0) return null;
  return (
    <Paper component="fieldset" sx={{ p: 2, mb: 2, border: "1px solid", borderColor: "divider" }}>
      <Typography component="legend" variant="subtitle2" sx={{ textTransform: "capitalize" }}>
        {slot}
      </Typography>
      {rows.map((f) => (
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
        </Box>
      ))}
    </Paper>
  );
}
