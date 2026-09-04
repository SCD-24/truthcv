import { useCallback, useEffect, useState } from "react";
import Box from "@mui/material/Box";
import Typography from "@mui/material/Typography";
import CircularProgress from "@mui/material/CircularProgress";
import Alert from "@mui/material/Alert";
import type { PromptFragment, PromptPreset } from "../api/client";
import { listPromptFragments, listPromptPresets } from "../api/client";
import { FragmentList } from "./FragmentList";
import { PresetBuilder } from "./PresetBuilder";

/** Human-readable message from a thrown value, with a fallback. */
function errText(e: unknown, fallback: string): string {
  return e instanceof Error ? e.message : fallback;
}

/**
 * WritingStylePage — the prompt library editor. Left panel manages the
 * fragment library (grouped by slot: voice, structure, opener, rules);
 * right panel builds and validates presets from those fragments. Both
 * panels reload from the server after any write, so the two stay in sync
 * without local mutation of server-owned state.
 */
export function WritingStylePage() {
  const [fragments, setFragments] = useState<PromptFragment[]>([]);
  const [presets, setPresets] = useState<PromptPreset[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const loadFragments = useCallback(() => {
    return listPromptFragments()
      .then(setFragments)
      .catch((e) => setError(errText(e, "Couldn't load fragments.")));
  }, []);

  const loadPresets = useCallback(() => {
    return listPromptPresets()
      .then(setPresets)
      .catch((e) => setError(errText(e, "Couldn't load presets.")));
  }, []);

  useEffect(() => {
    setLoading(true);
    Promise.all([loadFragments(), loadPresets()]).finally(() => setLoading(false));
  }, [loadFragments, loadPresets]);

  return (
    <section>
      <div className="stage__head">
        <Typography variant="overline" className="eyebrow">
          Writing Style
        </Typography>
        <h1 className="stage__title">Fragments &amp; presets</h1>
        <p className="stage__lede">
          Build the reusable text blocks the model draws on, then combine them
          into named presets for generation.
        </p>
      </div>

      {error && (
        <Alert severity="error" sx={{ mb: 3 }}>
          {error}
        </Alert>
      )}

      {loading ? (
        <Box role="status" aria-live="polite" sx={{ display: "flex", gap: 2, alignItems: "center" }}>
          <CircularProgress size={20} />
          <Typography variant="body1" sx={{ color: "text.secondary" }}>
            Loading fragments and presets…
          </Typography>
        </Box>
      ) : (
        <Box
          sx={{
            display: "grid",
            gridTemplateColumns: { xs: "1fr", md: "1fr 1fr" },
            gap: 3,
            alignItems: "start",
          }}
        >
          <FragmentList fragments={fragments} onChange={loadFragments} />
          <PresetBuilder
            fragments={fragments}
            presets={presets}
            onPresetsChange={loadPresets}
          />
        </Box>
      )}
    </section>
  );
}
