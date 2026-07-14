import { useEffect, useState } from "react";
import Dialog from "@mui/material/Dialog";
import DialogTitle from "@mui/material/DialogTitle";
import DialogContent from "@mui/material/DialogContent";
import DialogActions from "@mui/material/DialogActions";
import Box from "@mui/material/Box";
import Stack from "@mui/material/Stack";
import Button from "@mui/material/Button";
import IconButton from "@mui/material/IconButton";
import CloseIcon from "@mui/icons-material/Close";
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
import FormControlLabel from "@mui/material/FormControlLabel";
import Checkbox from "@mui/material/Checkbox";
import {
  createApplication,
  deleteApplication,
  listApplications,
  updateApplication,
} from "../api/client";
import type { Application, ApplicationCreate } from "../api/types";
import "../styles/applications.css";

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
};

/**
 * The applications ledger — an outbound record of every job the user is
 * pursuing and which CV/cover letter went out with it. Full CRUD against the
 * Application Tracker; documents are read-only here (they are attached from the
 * Download step) so this view stays a record, not a generator.
 */
export function ApplicationsModal({ onClose }: { onClose: () => void }) {
  const [apps, setApps] = useState<Application[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  // The row being edited: an id for an existing row, "new" for the add form.
  const [editing, setEditing] = useState<string | "new" | null>(null);
  const [draft, setDraft] = useState<ApplicationCreate>(EMPTY);
  const [saving, setSaving] = useState(false);

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
    <Dialog open onClose={onClose} maxWidth="xl" fullWidth aria-labelledby="apps-title">
      <DialogTitle
        id="apps-title"
        sx={{ display: "flex", alignItems: "flex-start", justifyContent: "space-between" }}
      >
        <Box>
          <Typography variant="overline" className="apps__eyebrow" sx={{ display: "block" }}>
            Outbound record
          </Typography>
          Applications
        </Box>
        <IconButton onClick={onClose} aria-label="Close applications" edge="end">
          <CloseIcon />
        </IconButton>
      </DialogTitle>

      <DialogContent dividers>
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
          <TableContainer>
            <Table size="small" className="apps__table">
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
                    />
                  ),
                )}
              </TableBody>
            </Table>
          </TableContainer>
        )}
      </DialogContent>

      <DialogActions>
        <Button variant="outlined" onClick={onClose}>
          Close
        </Button>
      </DialogActions>
    </Dialog>
  );
}

/** One ledger row, including the documents attached to the application. */
function ApplicationRow({
  app,
  onEdit,
  onDelete,
}: {
  app: Application;
  onEdit: () => void;
  onDelete: () => void;
}) {
  return (
    <TableRow hover>
      <TableCell className="apps__company">{app.company || "—"}</TableCell>
      <TableCell>{app.applicationDate || "—"}</TableCell>
      <TableCell>
        {app.website ? (
          <Link href={app.website} target="_blank" rel="noreferrer">
            {hostOf(app.website)}
          </Link>
        ) : (
          "—"
        )}
      </TableCell>
      <TableCell>
        {app.applicationUrl && app.applicationUrl !== "N/A" ? (
          <Link href={app.applicationUrl} target="_blank" rel="noreferrer">
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
        <DocumentLinks app={app} />
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

/** The CV/cover-letter files this application owns, as download links. */
function DocumentLinks({ app }: { app: Application }) {
  const cv = app.cvDocument;
  const cl = app.coverLetterDocument;
  if (!cv && !cl) return <span className="apps__none">—</span>;
  return (
    <Stack className="apps__docs" spacing={0.5}>
      {cv && <DocLine label="CV" pdf={cv.pdfUrl} docx={cv.docxUrl} />}
      {cl && <DocLine label="Cover" pdf={cl.pdfUrl} docx={cl.docxUrl} />}
    </Stack>
  );
}

function DocLine({
  label,
  pdf,
  docx,
}: {
  label: string;
  pdf: string | null;
  docx: string | null;
}) {
  return (
    <span>
      {label}:{" "}
      {pdf ? <Link href={pdf}>pdf</Link> : null}
      {pdf && docx ? " · " : null}
      {docx ? <Link href={docx}>docx</Link> : null}
      {!pdf && !docx ? "saved" : null}
    </span>
  );
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

/** Show a website as its bare host so the ledger stays scannable. */
function hostOf(url: string): string {
  try {
    return new URL(url).host;
  } catch {
    return url;
  }
}
