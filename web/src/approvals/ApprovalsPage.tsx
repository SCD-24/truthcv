import { useEffect, useState } from "react";
import Alert from "@mui/material/Alert";
import Box from "@mui/material/Box";
import Button from "@mui/material/Button";
import Checkbox from "@mui/material/Checkbox";
import Chip from "@mui/material/Chip";
import CircularProgress from "@mui/material/CircularProgress";
import Collapse from "@mui/material/Collapse";
import Divider from "@mui/material/Divider";
import FormControlLabel from "@mui/material/FormControlLabel";
import Link from "@mui/material/Link";
import Paper from "@mui/material/Paper";
import Stack from "@mui/material/Stack";
import TextField from "@mui/material/TextField";
import Typography from "@mui/material/Typography";
import ArrowBackIcon from "@mui/icons-material/ArrowBack";
import {
  bulkSetApproval,
  generateScreeningLetter,
  getScreeningLetter,
  listApprovedApplications,
  listDidNotPass,
  listPendingApprovals,
  listRejectedApprovals,
  saveScreeningLetter,
  setScreeningApproval,
  setScreeningUrl,
} from "../api/client";
import type { CoverLetterDraft, ScreeningRecord } from "../api/types";

/** The letter draft for one posting: fetches its own state on mount because
 * the list endpoint (GET /api/screenings) never carries drafts. Offers
 * Generate when there is none, an editable field with Save when there is —
 * the caption is the audit trail, since "generated" means the guardrail
 * checked this exact text and "operator" means the operator's words went in
 * unchecked. */
function CoverLetterSection({
  record,
  onDraftChange,
}: {
  record: ScreeningRecord;
  onDraftChange: (id: string, draft: CoverLetterDraft | null) => void;
}) {
  const [draft, setDraft] = useState<CoverLetterDraft | null>(null);
  const [loaded, setLoaded] = useState(false);
  const [text, setText] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [showPosting, setShowPosting] = useState(false);

  useEffect(() => {
    let live = true;
    getScreeningLetter(record.id).then((d) => {
      if (!live) return;
      setDraft(d);
      setText(d?.text ?? "");
      setLoaded(true);
      onDraftChange(record.id, d);
    });
    return () => {
      live = false;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [record.id]);

  async function generate() {
    setBusy(true);
    setError("");
    try {
      const d = await generateScreeningLetter(record.id);
      setDraft(d);
      setText(d.text);
      onDraftChange(record.id, d);
    } catch (e) {
      setError(String(e));
    } finally {
      setBusy(false);
    }
  }

  async function save() {
    setBusy(true);
    setError("");
    try {
      const d = await saveScreeningLetter(record.id, text);
      setDraft(d);
      setText(d.text);
      onDraftChange(record.id, d);
    } catch (e) {
      setError(String(e));
    } finally {
      setBusy(false);
    }
  }

  if (!loaded) return null;

  return (
    <Box sx={{ mt: 1 }}>
      {(record.postedDate || record.screenedDate) && (
        <Typography variant="body2" sx={{ color: "text.secondary" }}>
          {record.postedDate ? `Posted ${record.postedDate}` : null}
          {record.postedDate && record.screenedDate ? " · " : null}
          {record.screenedDate ? `Found ${record.screenedDate}` : null}
        </Typography>
      )}
      {record.postingText ? (
        <>
          <Button size="small" onClick={() => setShowPosting((s) => !s)} sx={{ mt: 0.5 }}>
            {showPosting ? "Hide posting text" : "Show posting text"}
          </Button>
          <Collapse in={showPosting}>
            <Typography
              variant="body2"
              sx={{ whiteSpace: "pre-wrap", color: "text.secondary", mt: 0.5 }}
            >
              {record.postingText}
            </Typography>
          </Collapse>
        </>
      ) : null}

      {error ? (
        <Alert severity="error" sx={{ mt: 1 }}>
          {error}
        </Alert>
      ) : null}

      {draft ? (
        <Stack spacing={1} sx={{ mt: 1 }}>
          <TextField
            label="Cover letter"
            multiline
            minRows={4}
            value={text}
            onChange={(e) => setText(e.target.value)}
          />
          <Stack direction="row" spacing={1} sx={{ alignItems: "center" }}>
            <Button
              variant="outlined"
              size="small"
              disabled={busy || !text.trim() || text === draft.text}
              onClick={save}
            >
              Save letter
            </Button>
            <Typography variant="caption" sx={{ color: "text.secondary" }}>
              {draft.source === "generated"
                ? "As generated — checked against your CV"
                : "Edited by you — saved as written, not checked"}
            </Typography>
          </Stack>
        </Stack>
      ) : (
        <Box sx={{ mt: 1 }}>
          <Button
            variant="outlined"
            size="small"
            disabled={busy || !record.postingText}
            onClick={generate}
          >
            Generate cover letter
          </Button>
          {!record.postingText ? (
            <Typography variant="body2" sx={{ color: "text.secondary", mt: 0.5 }}>
              No posting text was captured for this screening — there is nothing to draft from.
            </Typography>
          ) : null}
        </Box>
      )}
    </Box>
  );
}

/** Shown in place of the link when a record has no URL — postings imported
 * from the historical log carry none, and the agent cannot apply without one. */
function UrlEntry({
  busy,
  onSave,
}: {
  busy: boolean;
  onSave: (url: string) => void;
}) {
  const [url, setUrl] = useState("");
  return (
    <Stack direction="row" spacing={1} sx={{ mt: 1, alignItems: "center" }}>
      <TextField
        label="Posting URL"
        size="small"
        placeholder="https://..."
        value={url}
        onChange={(e) => setUrl(e.target.value)}
      />
      <Button
        variant="outlined"
        size="small"
        disabled={busy || !url.trim()}
        onClick={() => onSave(url)}
      >
        Save URL
      </Button>
    </Stack>
  );
}

/** One posting waiting on the operator: what the agent found, why it stopped,
 * and the two decisions available. */
function PendingCard({
  record,
  checked,
  busy,
  onToggle,
  onDecide,
  onSaveUrl,
}: {
  record: ScreeningRecord;
  checked: boolean;
  busy: boolean;
  onToggle: (id: string) => void;
  onDecide: (id: string, approval: "approved" | "rejected") => void;
  onSaveUrl: (id: string, url: string) => void;
}) {
  // The server enforces this at approval time too (PATCH 409s with no draft
  // stored) — this only makes the reason visible before the click.
  const [hasDraft, setHasDraft] = useState(false);
  return (
    <Paper variant="outlined" sx={{ p: 2 }}>
      <Stack direction="row" spacing={2} sx={{ alignItems: "flex-start" }}>
        <Checkbox
          checked={checked}
          onChange={() => onToggle(record.id)}
          slotProps={{ input: { "aria-label": `Select ${record.company}` } }}
        />
        <Box sx={{ flex: 1, minWidth: 0 }}>
          <Typography variant="subtitle1">{record.company}</Typography>
          <Typography variant="body2" sx={{ color: "text.secondary" }}>
            {record.role}
          </Typography>
          {record.url ? (
            <Link href={record.url} target="_blank" rel="noreferrer" variant="body2">
              {record.url}
            </Link>
          ) : (
            <UrlEntry busy={busy} onSave={(url) => onSaveUrl(record.id, url)} />
          )}
          <Stack direction="row" spacing={1} sx={{ mt: 1, alignItems: "center" }}>
            {record.failingCriterion ? (
              <Chip size="small" label={record.failingCriterion} />
            ) : null}
            <Typography variant="body2">{record.reason}</Typography>
          </Stack>
          <CoverLetterSection
            record={record}
            onDraftChange={(_id, draft) => setHasDraft(draft !== null)}
          />
        </Box>
        <Stack spacing={1}>
          <Button
            variant="contained"
            size="small"
            disabled={busy || !hasDraft}
            title={hasDraft ? undefined : "Draft a cover letter first"}
            onClick={() => onDecide(record.id, "approved")}
          >
            Approve
          </Button>
          <Button
            variant="outlined"
            size="small"
            disabled={busy}
            onClick={() => onDecide(record.id, "rejected")}
          >
            Reject
          </Button>
        </Stack>
      </Stack>
    </Paper>
  );
}

/** An approved item that has not been applied to yet. Its attempt count and
 * last error are the only signal that a posting is failing every run, which is
 * the manual drain for the retry-forever policy. */
function ApprovedRow({
  record,
  busy,
  onSaveUrl,
}: {
  record: ScreeningRecord;
  busy: boolean;
  onSaveUrl: (id: string, url: string) => void;
}) {
  return (
    <Paper variant="outlined" sx={{ p: 2 }}>
      <Typography variant="subtitle2">
        {record.company} — {record.role}
      </Typography>
      {record.url ? (
        <Link href={record.url} target="_blank" rel="noreferrer" variant="body2">
          {record.url}
        </Link>
      ) : (
        <>
          <Alert severity="warning" sx={{ mt: 1 }}>
            No URL — this posting cannot be applied to on the next run.
          </Alert>
          <UrlEntry busy={busy} onSave={(url) => onSaveUrl(record.id, url)} />
        </>
      )}
      <Typography variant="body2" sx={{ color: "text.secondary" }}>
        {record.applyAttempts} attempts
      </Typography>
      {record.applyError ? (
        <Alert severity="warning" sx={{ mt: 1 }}>
          {record.applyError}
        </Alert>
      ) : null}
    </Paper>
  );
}

/** A rejected or agent-filtered posting, reviewable and reversible: shows
 * why it was set aside and offers the one way back into the queue. */
function ReviewRow({
  record,
  busy,
  onMoveToApprovals,
}: {
  record: ScreeningRecord;
  busy: boolean;
  onMoveToApprovals: (id: string) => void;
}) {
  return (
    <Paper variant="outlined" sx={{ p: 2 }}>
      <Stack direction="row" spacing={2} sx={{ alignItems: "center" }}>
        <Box sx={{ flex: 1, minWidth: 0 }}>
          <Typography variant="subtitle1">{record.company}</Typography>
          <Typography variant="body2" sx={{ color: "text.secondary" }}>
            {record.role}
          </Typography>
          <Stack direction="row" spacing={1} sx={{ mt: 0.5, alignItems: "center" }}>
            {record.failingCriterion ? (
              <Chip size="small" label={record.failingCriterion} />
            ) : null}
            <Typography variant="body2" sx={{ color: "text.secondary" }}>
              {record.reason}
            </Typography>
          </Stack>
        </Box>
        <Button
          variant="outlined"
          size="small"
          disabled={busy}
          onClick={() => onMoveToApprovals(record.id)}
        >
          Move to approvals
        </Button>
      </Stack>
    </Paper>
  );
}

/** The operator's approval queue: postings the agent deferred, and the ones
 * already approved but not yet applied to. */
export function ApprovalsPage({ onBack }: { onBack: () => void }) {
  const [pending, setPending] = useState<ScreeningRecord[]>([]);
  const [approved, setApproved] = useState<ScreeningRecord[]>([]);
  const [rejected, setRejected] = useState<ScreeningRecord[]>([]);
  const [didNotPass, setDidNotPass] = useState<ScreeningRecord[]>([]);
  const [selected, setSelected] = useState<string[]>([]);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  useEffect(() => {
    let live = true;
    Promise.all([
      listPendingApprovals(),
      listApprovedApplications(),
      listRejectedApprovals(),
      listDidNotPass(),
    ])
      .then(([p, a, r, d]) => {
        if (!live) return;
        setPending(p);
        setApproved(a);
        setRejected(r);
        setDidNotPass(d);
      })
      .catch((e) => live && setError(String(e)))
      .finally(() => live && setLoading(false));
    return () => {
      live = false;
    };
  }, []);

  const toggle = (id: string) =>
    setSelected((s) => (s.includes(id) ? s.filter((x) => x !== id) : [...s, id]));

  const toggleAll = () =>
    setSelected((s) => (s.length === pending.length ? [] : pending.map((r) => r.id)));

  async function decide(id: string, approval: "approved" | "rejected") {
    setBusy(true);
    setError("");
    try {
      await setScreeningApproval(id, approval);
      setPending((rows) => rows.filter((r) => r.id !== id));
      setSelected((s) => s.filter((x) => x !== id));
    } catch (e) {
      setError(String(e));
    } finally {
      setBusy(false);
    }
  }

  async function decideSelected(approval: "approved" | "rejected") {
    setBusy(true);
    setError("");
    try {
      const { results } = await bulkSetApproval(selected, approval);
      const failed = new Set(results.filter((r) => !r.ok).map((r) => r.id));
      // Only clear the rows that actually changed: a partial failure must stay
      // visible rather than disappearing as if it had been decided.
      setPending((rows) =>
        rows.filter((r) => !selected.includes(r.id) || failed.has(r.id)),
      );
      setSelected([]);
      if (failed.size) setError(`${failed.size} could not be updated.`);
    } catch (e) {
      setError(String(e));
    } finally {
      setBusy(false);
    }
  }

  async function saveUrl(id: string, url: string) {
    setBusy(true);
    setError("");
    try {
      const updated = await setScreeningUrl(id, url);
      setPending((rows) => rows.map((r) => (r.id === id ? updated : r)));
      setApproved((rows) => rows.map((r) => (r.id === id ? updated : r)));
    } catch (e) {
      setError(String(e));
    } finally {
      setBusy(false);
    }
  }

  async function moveToApprovals(id: string) {
    setBusy(true);
    setError("");
    try {
      const updated = await setScreeningApproval(id, "pending");
      setRejected((rows) => rows.filter((r) => r.id !== id));
      setDidNotPass((rows) => rows.filter((r) => r.id !== id));
      setPending((rows) => [updated, ...rows]);
    } catch (e) {
      setError(String(e));
    } finally {
      setBusy(false);
    }
  }

  return (
    <Box>
      <Stack direction="row" spacing={1} sx={{ mb: 2, alignItems: "center" }}>
        <Button startIcon={<ArrowBackIcon />} onClick={onBack}>
          Back
        </Button>
        <Typography variant="h5">Approvals</Typography>
      </Stack>

      <Typography variant="body2" sx={{ color: "text.secondary", mb: 2 }}>
        Postings the agent could not decide alone. Approving one means it applies
        on the next scheduled run; cooldown and cover-letter truthfulness still
        apply.
      </Typography>

      {error ? (
        <Alert severity="error" sx={{ mb: 2 }}>
          {error}
        </Alert>
      ) : null}

      {loading ? (
        <CircularProgress />
      ) : pending.length === 0 &&
        approved.length === 0 &&
        rejected.length === 0 &&
        didNotPass.length === 0 ? (
        <Typography variant="body1">Nothing waiting.</Typography>
      ) : (
        <Stack spacing={2}>
          {pending.length > 0 ? (
            <>
              <Stack direction="row" spacing={2} sx={{ alignItems: "center" }}>
                <FormControlLabel
                  control={
                    <Checkbox
                      checked={selected.length === pending.length && pending.length > 0}
                      onChange={toggleAll}
                      slotProps={{ input: { "aria-label": "Select all" } }}
                    />
                  }
                  label="Select all"
                />
                <Button
                  variant="contained"
                  size="small"
                  disabled={busy || selected.length === 0}
                  onClick={() => decideSelected("approved")}
                >
                  Approve selected
                </Button>
                <Button
                  variant="outlined"
                  size="small"
                  disabled={busy || selected.length === 0}
                  onClick={() => decideSelected("rejected")}
                >
                  Reject selected
                </Button>
              </Stack>
              {pending.map((r) => (
                <PendingCard
                  key={r.id}
                  record={r}
                  checked={selected.includes(r.id)}
                  busy={busy}
                  onToggle={toggle}
                  onDecide={decide}
                  onSaveUrl={saveUrl}
                />
              ))}
            </>
          ) : (
            <Typography variant="body1">Nothing waiting.</Typography>
          )}

          {approved.length > 0 ? (
            <>
              <Divider />
              <Typography variant="subtitle1">Approved, not yet applied</Typography>
              {approved.map((r) => (
                <ApprovedRow key={r.id} record={r} busy={busy} onSaveUrl={saveUrl} />
              ))}
            </>
          ) : null}

          {didNotPass.length > 0 ? (
            <>
              <Divider />
              <Typography variant="subtitle1">Did not pass</Typography>
              {didNotPass.map((r) => (
                <ReviewRow key={r.id} record={r} busy={busy} onMoveToApprovals={moveToApprovals} />
              ))}
            </>
          ) : null}

          {rejected.length > 0 ? (
            <>
              <Divider />
              <Typography variant="subtitle1">Rejected</Typography>
              {rejected.map((r) => (
                <ReviewRow key={r.id} record={r} busy={busy} onMoveToApprovals={moveToApprovals} />
              ))}
            </>
          ) : null}
        </Stack>
      )}
    </Box>
  );
}
