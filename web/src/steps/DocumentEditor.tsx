import { useEffect, useState } from "react";
import Box from "@mui/material/Box";
import Button from "@mui/material/Button";
import Alert from "@mui/material/Alert";
import TextField from "@mui/material/TextField";
import MenuItem from "@mui/material/MenuItem";
import {
  createApplication,
  listApplications,
  saveApplicationCv,
  saveApplicationCoverLetter,
} from "../api/client";
import type { Application, SaveDocumentResult } from "../api/types";
import "../styles/editor.css";

type Kind = "cv" | "cover-letter";

/**
 * Edit a generated document and save it onto a tracked application. The user
 * tweaks the text, picks (or quickly creates) the application it went out with,
 * and saves — the backend re-runs the truthfulness guardrail before rendering,
 * so an edit that strays from the truth file is blocked, not shipped.
 *
 * When `lockedAppId` is given (re-editing a document opened from the ledger),
 * the save target is fixed to that application and the picker/create-new UI is
 * hidden, so a re-save updates the same application's document in place.
 */
export function DocumentEditor({
  kind,
  initial,
  lockedAppId,
}: {
  kind: Kind;
  initial: string;
  lockedAppId?: string;
}) {
  const [content, setContent] = useState(initial);
  const [apps, setApps] = useState<Application[]>([]);
  const [appId, setAppId] = useState<string>(lockedAppId ?? "");
  const [newCompany, setNewCompany] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [result, setResult] = useState<SaveDocumentResult | null>(null);

  // A generated document is the natural starting point; keep the editor in sync
  // if the user regenerates upstream.
  useEffect(() => setContent(initial), [initial]);

  // When re-editing a ledger document, keep the fixed target in sync if the
  // user opens a different saved document without unmounting the editor.
  useEffect(() => {
    if (lockedAppId) setAppId(lockedAppId);
  }, [lockedAppId]);

  useEffect(() => {
    listApplications()
      .then(setApps)
      .catch(() => setApps([]));
  }, []);

  const label = kind === "cv" ? "CV" : "cover letter";

  async function ensureApplication(): Promise<string | null> {
    if (appId) return appId;
    if (newCompany.trim()) {
      const created = await createApplication({ company: newCompany.trim() });
      setApps((prev) => [created, ...prev]);
      setAppId(created.id);
      setNewCompany("");
      return created.id;
    }
    return null;
  }

  async function save() {
    setBusy(true);
    setError(null);
    setResult(null);
    try {
      const target = await ensureApplication();
      if (!target) {
        setError("Pick an application or enter a company to save this to.");
        return;
      }
      const resp =
        kind === "cv"
          ? await saveApplicationCv(target, content)
          : await saveApplicationCoverLetter(target, content);
      setResult(resp);
      if (!resp.blocked && resp.application) {
        // Reflect the freshly-attached document in the picker list.
        setApps((prev) =>
          prev.map((a) => (a.id === resp.application!.id ? resp.application! : a)),
        );
      }
    } catch (e) {
      setError(e instanceof Error ? e.message : `Couldn't save the ${label}.`);
    } finally {
      setBusy(false);
    }
  }

  const savedDoc =
    result && !result.blocked && result.application
      ? kind === "cv"
        ? result.application.cvDocument
        : result.application.coverLetterDocument
      : null;

  return (
    <div className="editor">
      <div className="editor__head">
        <span className="editor__eyebrow">Edit &amp; save</span>
        <p className="editor__hint">
          Tweak the {label}, then save it to an application. Edits are still
          checked against your truth file before anything is written.
        </p>
      </div>

      <TextField
        className="editor__area"
        value={content}
        onChange={(e) => setContent(e.target.value)}
        aria-label={`Edit ${label}`}
        multiline
        minRows={kind === "cv" ? 16 : 12}
        fullWidth
        spellCheck
        sx={{ "& .MuiInputBase-input": { fontFamily: "var(--font-mono)", fontSize: "0.85rem" } }}
      />

      {lockedAppId ? (
        <Box className="editor__attach editor__attach--locked" sx={{ mt: 2 }}>
          <span className="editor__eyebrow">Saving to</span>
          <p className="editor__hint">
            {apps.find((a) => a.id === lockedAppId)?.company ||
              "this application"}
          </p>
        </Box>
      ) : (
        <Box
          className="editor__attach"
          sx={{ display: "flex", gap: 2, flexWrap: "wrap", mt: 2 }}
        >
          <TextField
            select
            label="Attach to application"
            value={appId}
            onChange={(e) => setAppId(e.target.value)}
            sx={{ minWidth: 220 }}
          >
            <MenuItem value="">— choose —</MenuItem>
            {apps.map((a) => (
              <MenuItem key={a.id} value={a.id}>
                {a.company || "(untitled)"}
              </MenuItem>
            ))}
          </TextField>
          {!appId && (
            <TextField
              label="…or new company"
              value={newCompany}
              onChange={(e) => setNewCompany(e.target.value)}
              placeholder="Create a new application"
              sx={{ minWidth: 220 }}
            />
          )}
        </Box>
      )}

      {error && (
        <Alert severity="error" sx={{ mt: 2 }}>
          {error}
        </Alert>
      )}

      {result?.blocked && (
        <div className="claims" role="group" aria-label="Blocked edits">
          <p className="claims__lede">
            These edits couldn&apos;t be traced to your truth file, so nothing was
            saved. Revise the text to match a real fact and save again.
          </p>
          {result.blockedClaims.map((c) => (
            <div className="claim" key={c.claimId}>
              <p className="claim__text">{c.text}</p>
              {c.tokens.length > 0 && (
                <p className="claim__tokens">
                  Couldn&apos;t trace:{" "}
                  {c.tokens.map((t) => (
                    <span className="claim__token" key={t}>
                      {t}
                    </span>
                  ))}
                </p>
              )}
            </div>
          ))}
        </div>
      )}

      {savedDoc && (
        <div className="editor__saved">
          <Alert
            severity={result?.renderUnavailable ? "warning" : "success"}
            sx={{ mt: 2, mb: 2 }}
          >
            {result?.renderUnavailable
              ? `Saved to ${result?.application?.company || "the application"}, but its PDF/DOCX couldn't be generated here — the render backend (WeasyPrint/pandoc) isn't installed. Run the Docker image to get downloadable files.`
              : `Saved to ${result?.application?.company || "the application"}.`}
          </Alert>
          <Box className="downloads" sx={{ display: "flex", gap: 2, flexWrap: "wrap" }}>
            {savedDoc.pdfUrl && (
              <Button variant="outlined" component="a" href={savedDoc.pdfUrl} download>
                {label} (PDF)
              </Button>
            )}
            {savedDoc.docxUrl && (
              <Button variant="outlined" component="a" href={savedDoc.docxUrl} download>
                {label} (DOCX)
              </Button>
            )}
          </Box>
        </div>
      )}

      <Box className="stage__actions" sx={{ display: "flex", gap: 2, mt: 2 }}>
        <Button variant="contained" disabled={busy} onClick={save}>
          {busy ? "Saving…" : `Save ${label} to application`}
        </Button>
      </Box>
    </div>
  );
}
