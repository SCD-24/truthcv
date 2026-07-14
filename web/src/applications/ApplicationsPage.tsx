import { useEffect, useState } from "react";
import Box from "@mui/material/Box";
import Stack from "@mui/material/Stack";
import Button from "@mui/material/Button";
import ArrowBackIcon from "@mui/icons-material/ArrowBack";
import Alert from "@mui/material/Alert";
import Chip from "@mui/material/Chip";
import Typography from "@mui/material/Typography";
import Table from "@mui/material/Table";
import TableHead from "@mui/material/TableHead";
import TableBody from "@mui/material/TableBody";
import TableRow from "@mui/material/TableRow";
import TableCell from "@mui/material/TableCell";
import TableContainer from "@mui/material/TableContainer";
import TextField from "@mui/material/TextField";
import MenuItem from "@mui/material/MenuItem";
import Link from "@mui/material/Link";
import Dialog from "@mui/material/Dialog";
import DialogTitle from "@mui/material/DialogTitle";
import DialogContent from "@mui/material/DialogContent";
import DialogActions from "@mui/material/DialogActions";
import FormControlLabel from "@mui/material/FormControlLabel";
import Checkbox from "@mui/material/Checkbox";
import {
  createApplication,
  deleteApplication,
  listApplications,
  updateApplication,
} from "../api/client";
import type {
  Application,
  ApplicationCreate,
  ApplicationDocument,
} from "../api/types";
import { DocumentAttachModal } from "./DocumentAttachModal";
import "../styles/applications.css";

type PreviewKind = "cv" | "cover-letter";

/** The columns the user asked to track, in order. */
const COLUMNS = [
  "Company",
  "Date",
  "Website",
  "Application URL",
  "Submitted",
  "Submission Type",
  "Reached Out",
  "To Who",
  "Response Received",
  "Method",
  "Notes",
  "Posting",
  "Documents",
  "",
] as const;

const EMPTY: ApplicationCreate = {
  company: "",
  website: "",
  applicationUrl: "",
  submitted: false,
  submissionType: "General",
  reachedOut: false,
  toWho: "",
  responseReceived: false,
  method: "",
  applicationDate: "",
  notes: "",
  posting: "",
};

/**
 * The applications ledger — an outbound record of every job the user is
 * pursuing and which CV/cover letter went out with it. Full CRUD against the
 * Application Tracker; documents are read-only here (they are attached from the
 * Download step) so this view stays a record, not a generator.
 *
 * Rendered as a full page inside the wizard stage (not a modal) so the outbound
 * record is a first-class view; `onBack` returns to the wizard step the user
 * left.
 */
export function ApplicationsPage({
  onBack,
  onEditDocument,
}: {
  onBack: () => void;
  /** Open the Download step (step 5) with a saved document loaded for editing. */
  onEditDocument: (req: {
    appId: string;
    kind: PreviewKind;
    source: string;
  }) => void;
}) {
  const [apps, setApps] = useState<Application[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  // The row being edited: an id for an existing row, "new" for the add form.
  const [editing, setEditing] = useState<string | "new" | null>(null);
  const [draft, setDraft] = useState<ApplicationCreate>(EMPTY);
  const [saving, setSaving] = useState(false);
  // The application + document kind currently open in the attach/edit modal.
  const [attach, setAttach] = useState<{ app: Application; kind: PreviewKind } | null>(
    null,
  );
  // The application whose job posting is open in the view/edit modal.
  const [posting, setPosting] = useState<Application | null>(null);

  /** Replace an application in the list after a document is attached/edited. */
  function applyAttached(updated: Application) {
    setApps((prev) => prev.map((a) => (a.id === updated.id ? updated : a)));
  }

  /** Save an edited job posting onto its application from the posting modal. */
  async function savePosting(id: string, text: string) {
    const updated = await updateApplication(id, { posting: text });
    applyAttached(updated);
    setPosting(null);
  }

  useEffect(() => {
    listApplications()
      .then(setApps)
      .catch((e) => setError(e instanceof Error ? e.message : "Couldn't load applications."))
      .finally(() => setLoading(false));
  }, []);

  function startAdd() {
    setDraft(EMPTY);
    setEditing("new");
  }

  function startEdit(app: Application) {
    setDraft({
      company: app.company,
      website: app.website,
      applicationUrl: app.applicationUrl,
      submitted: app.submitted,
      submissionType: app.submissionType,
      reachedOut: app.reachedOut,
      toWho: app.toWho,
      responseReceived: app.responseReceived,
      method: app.method,
      applicationDate: app.applicationDate,
      notes: app.notes,
      posting: app.posting,
    });
    setEditing(app.id);
  }

  async function save() {
    setSaving(true);
    setError(null);
    try {
      if (editing === "new") {
        const created = await createApplication(draft);
        setApps((prev) => [created, ...prev]);
      } else if (editing) {
        const updated = await updateApplication(editing, draft);
        setApps((prev) => prev.map((a) => (a.id === updated.id ? updated : a)));
      }
      setEditing(null);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Couldn't save the application.");
    } finally {
      setSaving(false);
    }
  }

  async function remove(id: string) {
    if (!confirm("Delete this application and its saved documents?")) return;
    setError(null);
    try {
      await deleteApplication(id);
      setApps((prev) => prev.filter((a) => a.id !== id));
    } catch (e) {
      setError(e instanceof Error ? e.message : "Couldn't delete the application.");
    }
  }

  return (
    <Box className="apps-page" aria-labelledby="apps-title">
      <Stack
        direction="row"
        className="apps-page__head"
        sx={{ mb: 3, alignItems: "flex-start", justifyContent: "space-between", gap: 2 }}
      >
        <Box>
          <Typography variant="overline" className="apps__eyebrow" sx={{ display: "block" }}>
            Outbound record
          </Typography>
          <Typography id="apps-title" variant="h4" component="h1" className="apps-page__title">
            Applications
          </Typography>
        </Box>
        <Button
          variant="text"
          startIcon={<ArrowBackIcon fontSize="small" />}
          onClick={onBack}
        >
          Back to wizard
        </Button>
      </Stack>

      <Stack
        direction="row"
        sx={{ mb: 2, alignItems: "center", justifyContent: "space-between" }}
      >
        <Typography variant="body2" color="text.secondary">
          {loading ? "Loading…" : `${apps.length} tracked`}
        </Typography>
        <Button variant="contained" onClick={startAdd} disabled={editing === "new"}>
          + Add application
        </Button>
      </Stack>

      {error && (
        <Alert severity="error" sx={{ mb: 2 }}>
          {error}
        </Alert>
      )}

      {editing === "new" && (
        <ApplicationForm
          draft={draft}
          setDraft={setDraft}
          saving={saving}
          onSave={save}
          onCancel={() => setEditing(null)}
        />
      )}

      {!loading && apps.length === 0 && editing !== "new" ? (
        <Typography color="text.secondary" sx={{ py: 4, textAlign: "center" }}>
          No applications yet. Add one to start tracking where your CVs go.
        </Typography>
      ) : (
        <TableContainer sx={{ width: "100%" }}>
          <Table size="small" className="apps__table" sx={{ width: "100%" }}>
            <TableHead>
              <TableRow>
                {COLUMNS.map((c) => (
                  <TableCell key={c || "actions"}>{c}</TableCell>
                ))}
              </TableRow>
            </TableHead>
            <TableBody>
              {apps.map((app) =>
                editing === app.id ? (
                  <TableRow key={app.id}>
                    <TableCell colSpan={COLUMNS.length}>
                      <ApplicationForm
                        draft={draft}
                        setDraft={setDraft}
                        saving={saving}
                        onSave={save}
                        onCancel={() => setEditing(null)}
                      />
                    </TableCell>
                  </TableRow>
                ) : (
                  <ApplicationRow
                    key={app.id}
                    app={app}
                    onEdit={() => startEdit(app)}
                    onDelete={() => remove(app.id)}
                    onOpenDocument={(kind, source) =>
                      onEditDocument({ appId: app.id, kind, source })
                    }
                    onAttach={(kind) => setAttach({ app, kind })}
                    onOpenPosting={() => setPosting(app)}
                  />
                ),
              )}
            </TableBody>
          </Table>
        </TableContainer>
      )}

      {attach && (
        <DocumentAttachModal
          kind={attach.kind}
          app={attach.app}
          onSaved={applyAttached}
          onClose={() => setAttach(null)}
        />
      )}

      {posting && (
        <PostingModal
          app={posting}
          saving={saving}
          onSave={savePosting}
          onClose={() => setPosting(null)}
        />
      )}
    </Box>
  );
}

/** One ledger row, including the documents attached to the application. */
function ApplicationRow({
  app,
  onEdit,
  onDelete,
  onOpenDocument,
  onAttach,
  onOpenPosting,
}: {
  app: Application;
  onEdit: () => void;
  onDelete: () => void;
  onOpenDocument: (kind: PreviewKind, source: string) => void;
  onAttach: (kind: PreviewKind) => void;
  onOpenPosting: () => void;
}) {
  return (
    <TableRow hover>
      <TableCell className="apps__company">{app.company || "—"}</TableCell>
      <TableCell>{app.applicationDate || "—"}</TableCell>
      <TableCell>
        {app.website ? (
          <Link href={absoluteUrl(app.website)} target="_blank" rel="noreferrer">
            {hostOf(app.website)}
          </Link>
        ) : (
          "—"
        )}
      </TableCell>
      <TableCell>
        {app.applicationUrl && app.applicationUrl !== "N/A" ? (
          <Link href={absoluteUrl(app.applicationUrl)} target="_blank" rel="noreferrer">
            link
          </Link>
        ) : (
          app.applicationUrl || "—"
        )}
      </TableCell>
      <TableCell>
        <Stamp on={app.submitted} yes="Submitted" no="Draft" />
      </TableCell>
      <TableCell>{app.submissionType || "—"}</TableCell>
      <TableCell>
        <Stamp on={app.reachedOut} yes="Yes" no="No" />
      </TableCell>
      <TableCell>{app.toWho || "—"}</TableCell>
      <TableCell>
        <Stamp on={app.responseReceived} yes="Replied" no="Waiting" />
      </TableCell>
      <TableCell>{app.method || "—"}</TableCell>
      <TableCell sx={{ maxWidth: 220, whiteSpace: "normal" }}>
        {app.notes || "—"}
      </TableCell>
      <TableCell>
        <PostingCell app={app} onOpen={onOpenPosting} />
      </TableCell>
      <TableCell>
        <DocumentLinks
          app={app}
          onOpenDocument={onOpenDocument}
          onAttach={onAttach}
        />
      </TableCell>
      <TableCell>
        <Stack direction="row" spacing={1}>
          <Button size="small" onClick={onEdit}>
            Edit
          </Button>
          <Button size="small" color="error" onClick={onDelete}>
            Delete
          </Button>
        </Stack>
      </TableCell>
    </TableRow>
  );
}

/**
 * The CV/cover-letter linked to this application. Each present document is a
 * clickable entry that opens it in the Download step for re-editing; absent
 * documents show a muted hint so it is always clear what is (and isn't) linked.
 */
function DocumentLinks({
  app,
  onOpenDocument,
  onAttach,
}: {
  app: Application;
  onOpenDocument: (kind: PreviewKind, source: string) => void;
  onAttach: (kind: PreviewKind) => void;
}) {
  return (
    <Stack className="apps__docs" spacing={0.75}>
      {app.cvDocument ? (
        <DocLine
          label="CV"
          doc={app.cvDocument}
          onOpen={() => onOpenDocument("cv", app.cvDocument!.source)}
        />
      ) : (
        <AddDocLine label="Add CV" onAdd={() => onAttach("cv")} />
      )}
      {app.coverLetterDocument ? (
        <DocLine
          label="Cover letter"
          doc={app.coverLetterDocument}
          onOpen={() =>
            onOpenDocument("cover-letter", app.coverLetterDocument!.source)
          }
        />
      ) : (
        <AddDocLine label="Add cover letter" onAdd={() => onAttach("cover-letter")} />
      )}
    </Stack>
  );
}

/**
 * The job posting linked to this application: a link that opens the posting
 * viewer/editor when set, or an actionable "add posting" affordance when empty
 * — mirroring how a CV or cover letter is linked.
 */
function PostingCell({ app, onOpen }: { app: Application; onOpen: () => void }) {
  if (!app.posting) {
    return (
      <div className="apps__docline">
        <Link
          component="button"
          type="button"
          onClick={onOpen}
          className="apps__docadd"
        >
          + Add posting
        </Link>
      </div>
    );
  }
  const firstLine = app.posting.split("\n").find((l) => l.trim()) ?? "Posting";
  return (
    <div className="apps__docline">
      <Link
        component="button"
        type="button"
        onClick={onOpen}
        className="apps__doclink"
        title="View or edit the job posting"
      >
        Posting
      </Link>
      <span className="apps__docmeta apps__postingpeek">
        {firstLine.slice(0, 60)}
        {firstLine.length > 60 ? "…" : ""}
      </span>
    </div>
  );
}

/**
 * View and edit an application's job posting. The posting is a plain-text field
 * on the record, edited here and saved via PUT /api/applications/{id}.
 */
function PostingModal({
  app,
  saving,
  onSave,
  onClose,
}: {
  app: Application;
  saving: boolean;
  onSave: (id: string, text: string) => void;
  onClose: () => void;
}) {
  const [text, setText] = useState(app.posting);
  return (
    <Dialog open onClose={onClose} maxWidth="sm" fullWidth>
      <DialogTitle>
        Job posting — {app.company || "application"}
      </DialogTitle>
      <DialogContent>
        <Typography variant="body2" color="text.secondary" sx={{ mb: 2 }}>
          The posting this application is for. Paste or edit it here.
        </Typography>
        <TextField
          value={text}
          onChange={(e) => setText(e.target.value)}
          multiline
          minRows={8}
          fullWidth
          autoFocus
          placeholder="Paste the job posting…"
        />
      </DialogContent>
      <DialogActions>
        <Button onClick={onClose} disabled={saving}>
          Cancel
        </Button>
        <Button
          variant="contained"
          onClick={() => onSave(app.id, text)}
          disabled={saving}
        >
          Save posting
        </Button>
      </DialogActions>
    </Dialog>
  );
}

/** An actionable "attach a document" line when none is linked yet. */
function AddDocLine({ label, onAdd }: { label: string; onAdd: () => void }) {
  return (
    <div className="apps__docline">
      <Link
        component="button"
        type="button"
        onClick={onAdd}
        className="apps__docadd"
      >
        + {label}
      </Link>
    </div>
  );
}

/** One linked document: an open-in-editor link (jumps to the Download step with
 * the saved content), quick pdf/docx downloads, and the saved date. */
function DocLine({
  label,
  doc,
  onOpen,
}: {
  label: string;
  doc: ApplicationDocument;
  onOpen: () => void;
}) {
  const saved = savedShort(doc.updatedAt);
  return (
    <div className="apps__docline">
      <Link
        component="button"
        type="button"
        onClick={onOpen}
        className="apps__doclink"
        title="Open in the editor to re-edit and re-save"
      >
        {label}
      </Link>
      <span className="apps__docmeta">
        {doc.pdfUrl && <Link href={doc.pdfUrl}>pdf</Link>}
        {doc.pdfUrl && doc.docxUrl ? " · " : null}
        {doc.docxUrl && <Link href={doc.docxUrl}>docx</Link>}
        {saved && <span className="apps__docdate">{saved}</span>}
      </span>
    </div>
  );
}

/** Short saved-date for the ledger; blank when the timestamp is unusable. */
function savedShort(iso: string): string {
  if (!iso) return "";
  const d = new Date(iso);
  return Number.isNaN(d.getTime()) ? "" : d.toLocaleDateString();
}

/**
 * A ledger status stamp. Seal-green (success) marks an attested/completed
 * state, oxblood (error) marks a still-open one — the project's semantic colors.
 */
function Stamp({ on, yes, no }: { on: boolean; yes: string; no: string }) {
  return (
    <Chip
      className="apps__stamp"
      size="small"
      variant="outlined"
      color={on ? "success" : "error"}
      label={on ? yes : no}
    />
  );
}

/** Add/edit form shared by the "new" row and inline row editing. */
function ApplicationForm({
  draft,
  setDraft,
  saving,
  onSave,
  onCancel,
}: {
  draft: ApplicationCreate;
  setDraft: (d: ApplicationCreate) => void;
  saving: boolean;
  onSave: () => void;
  onCancel: () => void;
}) {
  const set = <K extends keyof ApplicationCreate>(
    key: K,
    value: ApplicationCreate[K],
  ) => setDraft({ ...draft, [key]: value });

  return (
    <Box
      component="form"
      onSubmit={(e) => {
        e.preventDefault();
        onSave();
      }}
      sx={{ py: 1 }}
    >
      <Box
        sx={{
          display: "grid",
          gridTemplateColumns: "repeat(auto-fit, minmax(200px, 1fr))",
          gap: 2,
        }}
      >
        <TextField
          label="Company"
          value={draft.company ?? ""}
          onChange={(e) => set("company", e.target.value)}
          // eslint-disable-next-line jsx-a11y/no-autofocus
          autoFocus
          required
        />
        <TextField
          label="Date"
          type="date"
          value={draft.applicationDate ?? ""}
          onChange={(e) => set("applicationDate", e.target.value)}
          slotProps={{ inputLabel: { shrink: true } }}
        />
        <TextField
          label="Website"
          value={draft.website ?? ""}
          onChange={(e) => set("website", e.target.value)}
          placeholder="nagarro.com"
        />
        <TextField
          label="Application URL"
          value={draft.applicationUrl ?? ""}
          onChange={(e) => set("applicationUrl", e.target.value)}
          placeholder="N/A"
        />
        <TextField
          select
          label="Submission type"
          value={draft.submissionType ?? "General"}
          onChange={(e) => set("submissionType", e.target.value)}
        >
          <MenuItem value="General">General</MenuItem>
          <MenuItem value="Tailored">Tailored (to a posting)</MenuItem>
        </TextField>
        <TextField
          label="To who"
          value={draft.toWho ?? ""}
          onChange={(e) => set("toWho", e.target.value)}
          placeholder="Contact person"
        />
        <TextField
          label="Method"
          value={draft.method ?? ""}
          onChange={(e) => set("method", e.target.value)}
          placeholder="LinkedIn, Email…"
        />
      </Box>

      <TextField
        label="Notes"
        value={draft.notes ?? ""}
        onChange={(e) => set("notes", e.target.value)}
        multiline
        minRows={2}
        fullWidth
        sx={{ mt: 2 }}
        placeholder="Anything worth remembering about this application…"
      />

      <TextField
        label="Job posting"
        value={draft.posting ?? ""}
        onChange={(e) => set("posting", e.target.value)}
        multiline
        minRows={3}
        fullWidth
        sx={{ mt: 2 }}
        placeholder="Paste the job posting this application is for…"
      />

      <Stack direction="row" spacing={2} sx={{ mt: 1, flexWrap: "wrap" }}>
        <FormControlLabel
          control={
            <Checkbox
              checked={draft.submitted ?? false}
              onChange={(e) => set("submitted", e.target.checked)}
            />
          }
          label="Submitted"
        />
        <FormControlLabel
          control={
            <Checkbox
              checked={draft.reachedOut ?? false}
              onChange={(e) => set("reachedOut", e.target.checked)}
            />
          }
          label="Reached out"
        />
        <FormControlLabel
          control={
            <Checkbox
              checked={draft.responseReceived ?? false}
              onChange={(e) => set("responseReceived", e.target.checked)}
            />
          }
          label="Response received"
        />
      </Stack>

      <Stack direction="row" spacing={2} sx={{ mt: 2, justifyContent: "flex-end" }}>
        <Button variant="outlined" onClick={onCancel} disabled={saving}>
          Cancel
        </Button>
        <Button type="submit" variant="contained" disabled={saving}>
          {saving ? "Saving…" : "Save"}
        </Button>
      </Stack>
    </Box>
  );
}

/**
 * Make a user-entered link safe to use as an href.
 *
 * Users type bare hosts like "nagarro.com"; a scheme-less value is a RELATIVE
 * URL, so the browser would navigate inside the app instead of opening the
 * external site. Prepend https:// when there is no scheme, leaving already-
 * absolute URLs (and mailto:/tel:) untouched.
 */
function absoluteUrl(url: string): string {
  const trimmed = url.trim();
  if (/^[a-z][a-z0-9+.-]*:/i.test(trimmed)) return trimmed; // http(s):, mailto:, tel:, …
  return `https://${trimmed}`;
}

/** Show a website as its bare host so the ledger stays scannable. */
function hostOf(url: string): string {
  try {
    return new URL(absoluteUrl(url)).host;
  } catch {
    return url;
  }
}
