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
import Dialog from "@mui/material/Dialog";
import DialogTitle from "@mui/material/DialogTitle";
import DialogContent from "@mui/material/DialogContent";
import DialogActions from "@mui/material/DialogActions";
import FormControlLabel from "@mui/material/FormControlLabel";
import Checkbox from "@mui/material/Checkbox";
import TableSortLabel from "@mui/material/TableSortLabel";
import {
  APPLICATIONS_EXPORT_URL,
  createApplication,
  deleteApplication,
  listApplicationsPage,
  updateApplication,
} from "../api/client";
import type { Application, ApplicationCreate, ApplicationSortKey } from "../api/types";
import { DocumentAttachModal } from "./DocumentAttachModal";
import { ApplicationLinks } from "./ApplicationLinks";
import { COLUMN_DEFS, DEFAULT_SORT_COLUMN, DEFAULT_SORT_DIRECTION } from "./sorting";
import type { ColumnDef, SortDirection } from "./sorting";
import "../styles/applications.css";

type PreviewKind = "cv" | "cover-letter";

const EMPTY: ApplicationCreate = {
  company: "",
  website: "",
  applicationUrl: "",
  submitted: false,
  submissionType: "General",
  status: "",
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
  const APPLICATIONS_PAGE_SIZE = 25;

  const [page, setPage] = useState(0);
  const [total, setTotal] = useState(0);
  const [apps, setApps] = useState<Application[]>([]);
  const [loading, setLoading] = useState(true);
  const [query, setQuery] = useState("");
  const [debouncedQuery, setDebouncedQuery] = useState("");
  const SEARCH_DEBOUNCE_MS = 250;
  const [error, setError] = useState<string | null>(null);
  const [reloadKey, setReloadKey] = useState(0);
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
  // Newest applications first on load. The header reflects it, so the order is
  // visible and can be changed like any other column's.
  const [sortCol, setSortCol] = useState<ColumnDef | null>(DEFAULT_SORT_COLUMN);
  const [sortDir, setSortDir] = useState<SortDirection>(DEFAULT_SORT_DIRECTION);

  const pageCount = Math.max(1, Math.ceil(total / APPLICATIONS_PAGE_SIZE));

  // A record finishing/being deleted while you are on the last page can shrink the history out
  // from under the current page number. Step back rather than showing an
  // empty page with a Previous button as the only way out.
  useEffect(() => {
    if (page > 0 && page > pageCount - 1) setPage(pageCount - 1);
  }, [page, pageCount]);

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

  // The search box is debounced: the typed text lands in `debouncedQuery`
  // only after the operator pauses, and a new search always restarts at page 0
  // because the server's `total` (and so the pager) changes with the filter.
  useEffect(() => {
    const timer = setTimeout(() => {
      setDebouncedQuery(query);
      setPage(0);
    }, SEARCH_DEBOUNCE_MS);
    return () => clearTimeout(timer);
  }, [query]);

  useEffect(() => {
    let alive = true;
    // Polls are not serialised, so a request slower than the interval can
    // land after its own successor. Without an ordering guard that older
    // response wins, and it carries an older `total` — which shrinks
    // pageCount and can step the operator's page back under them.
    let latest = 0;

    function refresh() {
      const seq = ++latest;
      const sortKey = (sortCol?.sortKey as ApplicationSortKey) || "date";
      listApplicationsPage({
        limit: APPLICATIONS_PAGE_SIZE,
        offset: page * APPLICATIONS_PAGE_SIZE,
        sort: sortKey,
        direction: sortDir,
        q: debouncedQuery,
      })
        .then((result) => {
          if (!alive || seq !== latest) return;
          setApps(result.applications);
          setTotal(result.total);
          setError(null);
        })
        .catch((e: unknown) => {
          if (!alive || seq !== latest) return;
          setError(e instanceof Error ? e.message : "Couldn't load applications.");
        })
        .finally(() => {
          if (!alive || seq !== latest) return;
          setLoading(false);
        });
    }

    setLoading(true);
    refresh();
    return () => {
      alive = false;
    };
  }, [page, sortCol, sortDir, reloadKey, debouncedQuery]);

  /** Download the whole ledger as a zip (CSV + per-company document folders).
   * A plain navigation lets the browser stream the file straight to disk. */
  function exportApplications() {
    window.location.assign(APPLICATIONS_EXPORT_URL);
  }

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
      status: app.status,
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
        await createApplication(draft);
        // New applications change the list, so refetch the current page
        setReloadKey((k) => k + 1);
      } else if (editing) {
        const updated = await updateApplication(editing, draft);
        // Edited applications may stay on the current page; keep in-place replace
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
      // Deletion changes the list, so refetch the current page
      setReloadKey((k) => k + 1);
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
        <Stack direction="row" spacing={2} sx={{ alignItems: "center" }}>
          <Typography variant="body2" color="text.secondary">
            {loading ? "Loading…" : query !== "" ? `${total} matching` : `${apps.length} tracked`}
          </Typography>
          <TextField
            size="small"
            type="search"
            label="Search"
            placeholder="Company, notes, posting…"
            slotProps={{ input: { "aria-label": "Search applications" } }}
            value={query}
            onChange={(e) => setQuery(e.target.value)}
          />
        </Stack>
        <Stack direction="row" spacing={1}>
          <Button
            variant="outlined"
            onClick={exportApplications}
            disabled={apps.length === 0 && query === ""}
            title="Download the whole table as a CSV with documents grouped by company, zipped"
          >
            Export
          </Button>
          <Button variant="contained" onClick={startAdd} disabled={editing === "new"}>
            + Add application
          </Button>
        </Stack>
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

      {!loading && total === 0 && editing !== "new" ? (
        <Typography color="text.secondary" sx={{ py: 4, textAlign: "center" }}>
          {debouncedQuery
            ? "No applications match your search."
            : "No applications yet. Add one to start tracking where your CVs go."}
        </Typography>
      ) : loading && apps.length === 0 ? (
        <Typography variant="body2" color="text.secondary">
          Loading…
        </Typography>
      ) : (
        <>
          <TableContainer sx={{ width: "100%" }}>
            <Table size="small" className="apps__table" sx={{ width: "100%" }}>
              <TableHead>
                <TableRow>
                  {COLUMN_DEFS.map((c) => (
                    <TableCell key={c.label || "actions"}>
                      {c.sortable ? (
                        <TableSortLabel
                          active={sortCol?.label === c.label}
                          direction={sortCol?.label === c.label ? sortDir : "asc"}
                          onClick={() => {
                            if (sortCol?.label === c.label) setSortDir(sortDir === "asc" ? "desc" : "asc");
                            else {
                              setSortCol(c);
                              setSortDir("asc");
                              setPage(0);
                            }
                          }}
                        >
                          {c.label}
                        </TableSortLabel>
                      ) : (
                        c.label
                      )}
                    </TableCell>
                  ))}
                </TableRow>
              </TableHead>
              <TableBody>
                {apps.map((app) =>
                  editing === app.id ? (
                    <TableRow key={app.id}>
                      <TableCell colSpan={COLUMN_DEFS.length}>
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

          {total > 0 && (
            <Stack
              direction="row"
              spacing={2}
              sx={{ alignItems: "center", justifyContent: "flex-end", mt: 2, flexWrap: "wrap" }}
            >
              <Typography variant="caption" color="text.secondary">
                Page {page + 1} of {pageCount}
              </Typography>
              <Button
                size="small"
                disabled={page === 0}
                onClick={() => setPage((p) => Math.max(0, p - 1))}
              >
                Previous
              </Button>
              <Button
                size="small"
                disabled={page >= pageCount - 1}
                onClick={() => setPage((p) => Math.min(pageCount - 1, p + 1))}
              >
                Next
              </Button>
            </Stack>
          )}
        </>
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

/**
 * One ledger row, including the documents attached to the application.
 * Renders as a fragment with two rows: the main application data row, and a
 * sub-row containing the links spanning all columns.
 */
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
    <>
      <TableRow hover>
        <TableCell className="apps__company">
          <span className="apps__clip" title={app.company || undefined}>
            {app.company || "—"}
          </span>
        </TableCell>
        <TableCell>{app.applicationDate || "—"}</TableCell>
        <TableCell>
          <Stamp on={app.submitted} yes="Submitted" no="Draft" />
        </TableCell>
        <TableCell>{app.submissionType || "—"}</TableCell>
        <TableCell>
          {app.status ? (
            <Chip
              className="apps__stamp"
              size="small"
              variant="outlined"
              color={statusColor(app.status)}
              label={app.status}
            />
          ) : (
            "—"
          )}
        </TableCell>
        <TableCell>
          <Stamp on={app.reachedOut} yes="Yes" no="No" />
        </TableCell>
        <TableCell className="apps__clip" title={app.toWho || undefined}>
          {app.toWho || "—"}
        </TableCell>
        <TableCell>
          <Stamp on={app.responseReceived} yes="Replied" no="Waiting" />
        </TableCell>
        <TableCell className="apps__clip" title={app.method || undefined}>
          {app.method || "—"}
        </TableCell>
        <TableCell sx={{ maxWidth: 220 }}>
          <Box
            sx={{
              whiteSpace: "normal",
              display: "-webkit-box",
              WebkitLineClamp: 2,
              WebkitBoxOrient: "vertical",
              overflow: "hidden",
            }}
          >
            {app.notes || "—"}
          </Box>
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
      <TableRow className="apps__subrow">
        <TableCell colSpan={COLUMN_DEFS.length} className="apps__subcell">
          <ApplicationLinks
            app={app}
            onOpenDocument={onOpenDocument}
            onAttach={onAttach}
            onOpenPosting={onOpenPosting}
          />
        </TableCell>
      </TableRow>
    </>
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

/**
 * A ledger status stamp. Seal-green (success) marks an attested/completed
 * state, oxblood (error) marks a still-open one — the project's semantic colors.
 * A "waiting" negative is amber instead: nothing is wrong yet, it is only unresolved.
 */
function Stamp({ on, yes, no }: { on: boolean; yes: string; no: string }) {
  const off = no === "Waiting" ? "warning" : "error";
  return (
    <Chip
      className="apps__stamp"
      size="small"
      variant="outlined"
      color={on ? "success" : off}
      label={on ? yes : no}
    />
  );
}

/**
 * Maps a free-text status onto the ledger's semantic stamp colors so the column
 * reads like the rest of the row instead of defaulting to grey. Waiting states
 * are amber; anything unrecognised stays neutral.
 */
function statusColor(
  status: string,
): "default" | "success" | "error" | "warning" | "info" {
  switch (status) {
    case "Offer":
      return "success";
    case "Rejected":
    case "Draft":
      return "error";
    case "Waiting":
      return "warning";
    case "Applied":
    case "Interviewing":
      return "info";
    default:
      return "default";
  }
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
          placeholder="vandelay.example"
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
          select
          label="Status"
          value={draft.status ?? ""}
          onChange={(e) => set("status", e.target.value)}
        >
          <MenuItem value="">Unset</MenuItem>
          <MenuItem value="Draft">Draft</MenuItem>
          <MenuItem value="Applied">Applied</MenuItem>
          <MenuItem value="Waiting">Waiting</MenuItem>
          <MenuItem value="Interviewing">Interviewing</MenuItem>
          <MenuItem value="Offer">Offer</MenuItem>
          <MenuItem value="Rejected">Rejected</MenuItem>
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


