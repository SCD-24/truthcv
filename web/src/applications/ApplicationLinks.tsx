import Link from "@mui/material/Link";
import Typography from "@mui/material/Typography";
import Stack from "@mui/material/Stack";
import { Link as RouterLink } from "react-router-dom";
import type {
  Application,
  ApplicationDocument,
  PreviewKind,
} from "../api/types";
import { safeHref } from "../utils/safeUrl";
import { filledFormPath } from "../routes";

/**
 * The quick-links row for one application in the ledger: website, application
 * URL, job posting, CV/cover-letter documents, and the filled-form evidence
 * page. Each item is either a live link/action or a compact "add" affordance,
 * so the row always shows what is (and isn't) linked without a modal.
 */
export function ApplicationLinks({
  app,
  onOpenDocument,
  onAttach,
  onOpenPosting,
}: {
  app: Application;
  onOpenDocument: (kind: PreviewKind, source: string) => void;
  onAttach: (kind: PreviewKind) => void;
  onOpenPosting: () => void;
}) {
  const fieldCount = app.fieldsSubmitted?.length ?? 0;
  return (
    <Stack
      direction="row"
      spacing={1.5}
      className="apps__links"
      sx={{ flexWrap: "nowrap", alignItems: "center" }}
    >
      <ExternalLink label="Website" href={app.website} />
      <ExternalLink label="URL" href={app.applicationUrl} />
      <PostingLink app={app} onOpen={onOpenPosting} />
      <DocumentLink
        label="CV"
        addLabel="+ Add CV"
        kind="cv"
        doc={app.cvDocument}
        onOpen={onOpenDocument}
        onAttach={onAttach}
      />
      <DocumentLink
        label="Cover letter"
        addLabel="+ Add cover letter"
        kind="cover-letter"
        doc={app.coverLetterDocument}
        onOpen={onOpenDocument}
        onAttach={onAttach}
      />
      {fieldCount > 0 && (
        <div className="apps__docline">
          <Link
            component={RouterLink}
            to={filledFormPath(app.id)}
            className="apps__doclink"
            title="View the fields the agent recorded for this application"
          >
            Filled form
          </Link>
          <span className="apps__docmeta">{fieldCount} field(s)</span>
        </div>
      )}
    </Stack>
  );
}

/**
 * A safe external link for a website/URL field: a real `target=_blank` anchor
 * when `safeHref` accepts the value (matching the ledger table's own website/
 * URL columns), an inert (non-clickable) label showing the raw value when the
 * scheme is rejected, and nothing at all when the field is blank or the "N/A"
 * placeholder.
 */
function ExternalLink({ label, href }: { label: string; href: string }) {
  const trimmed = (href ?? "").trim();
  if (!trimmed || trimmed === "N/A") return null;
  const safe = safeHref(trimmed);
  if (!safe) {
    return (
      <Typography variant="body2" color="text.secondary" className="apps__docmeta">
        {trimmed}
      </Typography>
    );
  }
  return (
    <Link
      href={safe}
      target="_blank"
      rel="noreferrer"
      className="apps__doclink"
      aria-label={`Open ${label.toLowerCase()}: ${safe}`}
    >
      {label}
    </Link>
  );
}

/**
 * The job posting link/action for an application: opens the posting
 * viewer/editor when one is set, or offers to add one when it isn't.
 */
function PostingLink({ app, onOpen }: { app: Application; onOpen: () => void }) {
  if (!app.posting) {
    return (
      <Link
        component="button"
        type="button"
        onClick={onOpen}
        className="apps__docadd"
      >
        + Add posting
      </Link>
    );
  }
  return (
    <Link
      component="button"
      type="button"
      onClick={onOpen}
      className="apps__doclink"
      title="View or edit the job posting"
    >
      Posting
    </Link>
  );
}

/**
 * One linked document (CV or cover letter): an open-in-editor link with
 * pdf/docx downloads and the saved date when present, or an "add" action
 * when the application has none yet.
 */
function DocumentLink({
  label,
  addLabel,
  kind,
  doc,
  onOpen,
  onAttach,
}: {
  label: string;
  addLabel: string;
  kind: PreviewKind;
  doc: ApplicationDocument | null;
  onOpen: (kind: PreviewKind, source: string) => void;
  onAttach: (kind: PreviewKind) => void;
}) {
  if (!doc) {
    return (
      <Link
        component="button"
        type="button"
        onClick={() => onAttach(kind)}
        className="apps__docadd"
      >
        {addLabel}
      </Link>
    );
  }
  const saved = savedShort(doc.updatedAt);
  return (
    <div className="apps__docline">
      <Link
        component="button"
        type="button"
        onClick={() => onOpen(kind, doc.source)}
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

/** Short saved-date for a document line; blank when the timestamp is unusable. */
function savedShort(iso: string): string {
  if (!iso) return "";
  const d = new Date(iso);
  return Number.isNaN(d.getTime()) ? "" : d.toLocaleDateString();
}
