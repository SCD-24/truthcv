import Dialog from "@mui/material/Dialog";
import DialogTitle from "@mui/material/DialogTitle";
import DialogContent from "@mui/material/DialogContent";
import DialogActions from "@mui/material/DialogActions";
import Box from "@mui/material/Box";
import Button from "@mui/material/Button";
import IconButton from "@mui/material/IconButton";
import CloseIcon from "@mui/icons-material/Close";
import Typography from "@mui/material/Typography";
import type { ApplicationDocument } from "../api/types";

type Kind = "cv" | "cover-letter";

/** Human label for a document kind. */
function kindLabel(kind: Kind): string {
  return kind === "cv" ? "CV" : "Cover letter";
}

/** Format an ISO timestamp for the saved-date eyebrow; blank if unparseable. */
function savedLabel(iso: string): string {
  if (!iso) return "";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return "";
  return `Saved ${d.toLocaleString()}`;
}

/**
 * Preview ONE saved document exactly as it was recorded on the application.
 *
 * The CV `source` is the rendered HTML that shipped, so it is shown in a
 * sandboxed iframe — this isolates it from the app's own styles and, because
 * the sandbox grants no scripts/same-origin, safely renders stored markup. The
 * cover letter `source` is plain text, shown preformatted with wrapping. The
 * pdf/docx download links for what actually went out sit in the actions bar.
 */
export function DocumentPreviewModal({
  kind,
  company,
  doc,
  onClose,
}: {
  kind: Kind;
  company: string;
  doc: ApplicationDocument;
  onClose: () => void;
}) {
  const saved = savedLabel(doc.updatedAt);
  const heading = `${company || "Application"} — ${kindLabel(kind)}`;

  return (
    <Dialog open onClose={onClose} maxWidth="md" fullWidth scroll="paper">
      <DialogTitle sx={{ pr: 6 }}>
        {saved && (
          <Typography
            variant="overline"
            className="apps__eyebrow"
            sx={{ display: "block" }}
          >
            {saved}
          </Typography>
        )}
        {heading}
        <IconButton
          aria-label="Close preview"
          onClick={onClose}
          sx={{ position: "absolute", right: 8, top: 8 }}
        >
          <CloseIcon />
        </IconButton>
      </DialogTitle>

      <DialogContent dividers>
        {kind === "cv" ? (
          <Box
            component="iframe"
            title={heading}
            srcDoc={doc.source}
            sandbox=""
            sx={{
              width: "100%",
              minHeight: "60vh",
              border: "1px solid var(--line)",
              borderRadius: "var(--radius)",
              background: "#fff",
            }}
          />
        ) : (
          <Box
            component="pre"
            sx={{
              m: 0,
              whiteSpace: "pre-wrap",
              wordBreak: "break-word",
              fontFamily: "var(--font-body)",
              fontSize: "var(--step--1)",
              lineHeight: 1.6,
              color: "text.primary",
            }}
          >
            {doc.source || "No saved text."}
          </Box>
        )}
      </DialogContent>

      <DialogActions>
        {doc.pdfUrl && (
          <Button href={doc.pdfUrl} variant="outlined">
            Download PDF
          </Button>
        )}
        {doc.docxUrl && (
          <Button href={doc.docxUrl} variant="outlined">
            Download DOCX
          </Button>
        )}
        <Button onClick={onClose} variant="contained">
          Close
        </Button>
      </DialogActions>
    </Dialog>
  );
}
