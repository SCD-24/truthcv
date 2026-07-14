import { useState } from "react";
import Dialog from "@mui/material/Dialog";
import DialogTitle from "@mui/material/DialogTitle";
import DialogContent from "@mui/material/DialogContent";
import DialogActions from "@mui/material/DialogActions";
import Button from "@mui/material/Button";
import IconButton from "@mui/material/IconButton";
import CloseIcon from "@mui/icons-material/Close";
import Typography from "@mui/material/Typography";
import TextField from "@mui/material/TextField";
import Alert from "@mui/material/Alert";
import { saveApplicationCv, saveApplicationCoverLetter } from "../api/client";
import type { Application, SaveDocumentResult } from "../api/types";

type Kind = "cv" | "cover-letter";

/** Human label for a document kind. */
function kindLabel(kind: Kind): string {
  return kind === "cv" ? "CV" : "Cover letter";
}

/**
 * Attach — or re-edit — one document on an application straight from the ledger.
 *
 * A manually-created application has no generated document to fall back on, so
 * this is the only way to give it a CV or cover letter. A manual edit is a
 * deliberate human decision, so it is trusted and saved as-is (the truthfulness
 * guardrail only gates the automatic AI generation, not hand-edited text). The
 * CV source is HTML; the cover letter is plain text (matching PUT /cv {html}
 * and /cover-letter {text}).
 */
export function DocumentAttachModal({
  kind,
  app,
  onSaved,
  onClose,
}: {
  kind: Kind;
  app: Application;
  onSaved: (app: Application) => void;
  onClose: () => void;
}) {
  const existing = kind === "cv" ? app.cvDocument : app.coverLetterDocument;
  const [content, setContent] = useState(existing?.source ?? "");
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [result, setResult] = useState<SaveDocumentResult | null>(null);

  const label = kindLabel(kind);
  const verb = existing ? "Edit" : "Add";
  const heading = `${app.company || "Application"} — ${verb} ${label.toLowerCase()}`;
  const placeholder =
    kind === "cv"
      ? "Paste the CV HTML that went out with this application…"
      : "Paste or write the cover-letter text…";

  async function save() {
    if (!content.trim()) {
      setError(`Enter the ${label.toLowerCase()} before saving.`);
      return;
    }
    setSaving(true);
    setError(null);
    setResult(null);
    try {
      const resp =
        kind === "cv"
          ? await saveApplicationCv(app.id, content)
          : await saveApplicationCoverLetter(app.id, content);
      if (!resp.blocked && resp.application) {
        onSaved(resp.application);
        // The document IS saved. Only close silently when it also rendered; if
        // the render backend was unavailable, keep the dialog open to explain
        // why no PDF/DOCX links appeared (the source was still attached).
        if (!resp.renderUnavailable) {
          onClose();
          return;
        }
      }
      // Blocked, or saved-without-render: keep the dialog open with the result.
      setResult(resp);
    } catch (e) {
      setError(e instanceof Error ? e.message : `Couldn't save the ${label.toLowerCase()}.`);
    } finally {
      setSaving(false);
    }
  }

  return (
    <Dialog open onClose={onClose} maxWidth="md" fullWidth scroll="paper">
      <DialogTitle sx={{ pr: 6 }}>
        <Typography
          variant="overline"
          className="apps__eyebrow"
          sx={{ display: "block" }}
        >
          {verb === "Edit" ? "Edit & save" : "Attach & save"}
        </Typography>
        {heading}
        <IconButton
          aria-label="Close"
          onClick={onClose}
          sx={{ position: "absolute", right: 8, top: 8 }}
        >
          <CloseIcon />
        </IconButton>
      </DialogTitle>

      <DialogContent dividers>
        <Typography
          variant="body2"
          color="text.secondary"
          sx={{ mb: 2 }}
        >
          Your edits are trusted and saved as-is to this application.
        </Typography>

        <TextField
          value={content}
          onChange={(e) => setContent(e.target.value)}
          aria-label={`Edit ${label.toLowerCase()}`}
          multiline
          minRows={kind === "cv" ? 16 : 12}
          fullWidth
          spellCheck
          placeholder={placeholder}
          sx={{
            "& .MuiInputBase-input": {
              fontFamily: "var(--font-mono)",
              fontSize: "0.85rem",
            },
          }}
        />

        {error && (
          <Alert severity="error" sx={{ mt: 2 }}>
            {error}
          </Alert>
        )}

        {result && !result.blocked && result.renderUnavailable && (
          <Alert severity="warning" sx={{ mt: 2 }}>
            Saved to this application, but its PDF/DOCX couldn&apos;t be generated
            here — the render backend (WeasyPrint/pandoc) isn&apos;t installed. Run
            the Docker image to get downloadable files.
          </Alert>
        )}

      </DialogContent>

      <DialogActions>
        <Button variant="outlined" onClick={onClose} disabled={saving}>
          Cancel
        </Button>
        <Button variant="contained" onClick={save} disabled={saving}>
          {saving ? "Saving…" : `Save ${label.toLowerCase()}`}
        </Button>
      </DialogActions>
    </Dialog>
  );
}
