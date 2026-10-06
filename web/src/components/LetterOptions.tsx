import FormControl from "@mui/material/FormControl";
import Select, { type SelectChangeEvent } from "@mui/material/Select";
import MenuItem from "@mui/material/MenuItem";
import EditOutlinedIcon from "@mui/icons-material/EditOutlined";
import { Link as RouterLink } from "react-router-dom";
import type { PromptPreset } from "../api/client";
import { ROUTES } from "../routes";
import "../styles/step.css";

/** The selectable cover-letter lengths. */
export const LENGTHS = ["Short", "Standard"] as const;
/** One of the selectable cover-letter lengths. */
export type Length = (typeof LENGTHS)[number];

/** A labelled row of toggle buttons (ported from DownloadStep's tone/length). */
export function ChoiceGroup<T extends string>({
  label,
  options,
  value,
  onChange,
}: {
  label: string;
  options: readonly T[];
  value: T;
  onChange: (v: T) => void;
}) {
  return (
    <div className="choice-group">
      <span className="field__label">{label}</span>
      <div className="choice-row">
        {options.map((o) => (
          <button
            key={o}
            type="button"
            className="choice__btn"
            data-active={o === value}
            aria-pressed={o === value}
            onClick={() => onChange(o)}
          >
            {o}
          </button>
        ))}
      </div>
    </div>
  );
}

/** The label above the style picker, with a small link to the preset editor. */
function StyleLabel() {
  return (
    <span
      className="field__label"
      style={{ display: "inline-flex", alignItems: "center", gap: 4 }}
    >
      Style
      <RouterLink
        to={ROUTES.writingStyle}
        aria-label="Manage writing styles"
        title="Manage writing styles"
        style={{ display: "inline-flex", color: "inherit" }}
      >
        <EditOutlinedIcon fontSize="inherit" />
      </RouterLink>
    </span>
  );
}

/** Picks a prompt preset (the letter's "style"). A dropdown once there are
 * more than a handful of presets to keep the page from sprawling; otherwise
 * the same toggle-button row used for tone/length. */
export function StyleSelector({
  presets,
  selectedPresetId,
  onChange,
}: {
  presets: PromptPreset[];
  selectedPresetId: string | null;
  onChange: (id: string) => void;
}) {
  if (presets.length > 5) {
    return (
      <FormControl size="small" sx={{ minWidth: 220, mb: 2 }}>
        <StyleLabel />
        <Select
          value={selectedPresetId ?? ""}
          onChange={(e: SelectChangeEvent) => onChange(e.target.value)}
          displayEmpty
        >
          {presets.map((p) => (
            <MenuItem key={p.id} value={p.id}>
              {p.name}
            </MenuItem>
          ))}
        </Select>
      </FormControl>
    );
  }

  return (
    <div className="choice-group">
      <StyleLabel />
      <div className="choice-row">
        {presets.map((p) => (
          <button
            key={p.id}
            type="button"
            className="choice__btn"
            data-active={p.id === selectedPresetId}
            aria-pressed={p.id === selectedPresetId}
            onClick={() => onChange(p.id)}
          >
            {p.name}
          </button>
        ))}
      </div>
    </div>
  );
}
