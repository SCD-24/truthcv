import { useEffect, useState } from "react";
import Alert from "@mui/material/Alert";
import Box from "@mui/material/Box";
import Button from "@mui/material/Button";
import Checkbox from "@mui/material/Checkbox";
import Chip from "@mui/material/Chip";
import CircularProgress from "@mui/material/CircularProgress";
import Collapse from "@mui/material/Collapse";
import Dialog from "@mui/material/Dialog";
import DialogActions from "@mui/material/DialogActions";
import DialogContent from "@mui/material/DialogContent";
import DialogContentText from "@mui/material/DialogContentText";
import DialogTitle from "@mui/material/DialogTitle";
import FormControlLabel from "@mui/material/FormControlLabel";
import Link from "@mui/material/Link";
import Paper from "@mui/material/Paper";
import Stack from "@mui/material/Stack";
import Tab from "@mui/material/Tab";
import Tabs from "@mui/material/Tabs";
import TextField from "@mui/material/TextField";
import Typography from "@mui/material/Typography";
import ArrowBackIcon from "@mui/icons-material/ArrowBack";
import { isCooldownActive } from "../settings/cooldown";
import { cooldownBlockLabel } from "../screenings/ScreeningsPage";
import {
  bulkDeleteScreenings,
  bulkSetApproval,
  deleteScreening,
  generateScreeningLetter,
  getScreeningLetter,
  markScreeningApplied,
  listAppliedScreenings,
  listApprovedApplications,
  listDidNotPass,
  listPendingApprovals,
  listRejectedApprovals,
  saveScreeningLetter,
  setScreeningApproval,
  setScreeningPostingText,
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
  const [postingText, setPostingText] = useState(record.postingText);
  const [postingTextDraft, setPostingTextDraft] = useState("");

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

  async function savePostingText() {
    setBusy(true);
    setError("");
    try {
      const r = await setScreeningPostingText(record.id, postingTextDraft);
      setPostingText(r.postingText);
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
      {postingText ? (
        <>
          <Button size="small" onClick={() => setShowPosting((s) => !s)} sx={{ mt: 0.5 }}>
            {showPosting ? "Hide posting text" : "Show posting text"}
          </Button>
          <Collapse in={showPosting}>
            <Typography
              variant="body2"
              sx={{ whiteSpace: "pre-wrap", color: "text.secondary", mt: 0.5 }}
            >
              {postingText}
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
                ? "As generated — checked against your truth file before sending."
                : "Your words — not checked against the truth file."}
            </Typography>
          </Stack>
        </Stack>
      ) : (
        <Button
          variant="outlined"
          size="small"
          disabled={busy || !postingText}
          onClick={generate}
        >
          Generate cover letter
        </Button>
      )}
      {!draft && !postingText ? (
        <Typography variant="body2" sx={{ color: "text.secondary", mt: 0.5 }}>
          No posting text was captured for this screening — there is nothing to draft from.
        </Typography>
      ) : null}
      {!postingText ? (
        <Stack spacing={1} sx={{ mt: 1 }}>
          <TextField
            label="Posting text"
            multiline
            minRows={4}
            value={postingTextDraft}
            onChange={(e) => setPostingTextDraft(e.target.value)}
          />
          <Button
            variant="outlined"
            size="small"
            disabled={busy || !postingTextDraft.trim()}
            onClick={savePostingText}
          >
            Save posting text
          </Button>
        </Stack>
      ) : null}
    </Box>
  );
}

/** The posting URL, in both states it can be in: empty (postings imported
 * from the historical log carry none, and the agent cannot apply without
 * one) or already set, in which case it shows as a link with an Edit URL
 * button that reveals the field prefilled with the current value. The field
 * stays unmounted until Edit is clicked. */
function PostingUrl({
  url,
  busy,
  onSave,
}: {
  url: string;
  busy: boolean;
  onSave: (url: string) => void;
}) {
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState(url);

  if (!url) {
    return (
      <Stack direction="row" spacing={1} sx={{ mt: 1, alignItems: "center" }}>
        <TextField
          label="Posting URL"
          size="small"
          placeholder="https://..."
          value={draft}
          onChange={(e) => setDraft(e.target.value)}
        />
        <Button
          variant="outlined"
          size="small"
          disabled={busy || !draft.trim()}
          onClick={() => onSave(draft)}
        >
          Save URL
        </Button>
      </Stack>
    );
  }

  if (!editing) {
    return (
      <Stack direction="row" spacing={1} sx={{ alignItems: "center" }}>
        <Link href={url} target="_blank" rel="noreferrer" variant="body2">
          {url}
        </Link>
        <Button
          size="small"
          onClick={() => {
            setDraft(url);
            setEditing(true);
          }}
        >
          Edit URL
        </Button>
      </Stack>
    );
  }

  return (
    <Stack direction="row" spacing={1} sx={{ mt: 1, alignItems: "center" }}>
      <TextField
        label="Posting URL"
        size="small"
        placeholder="https://..."
        value={draft}
        onChange={(e) => setDraft(e.target.value)}
      />
      <Button
        variant="outlined"
        size="small"
        disabled={busy || !draft.trim()}
        onClick={() => {
          onSave(draft);
          setEditing(false);
        }}
      >
        Save URL
      </Button>
      <Button
        size="small"
        onClick={() => {
          setDraft(url);
          setEditing(false);
        }}
      >
        Cancel
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
  onMarkApplied,
}: {
  record: ScreeningRecord;
  checked: boolean;
  busy: boolean;
  onToggle: (id: string) => void;
  onDecide: (id: string, approval: "approved" | "rejected") => void;
  onSaveUrl: (id: string, url: string) => void;
  onMarkApplied: (id: string) => void;
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
          <PostingUrl
            url={record.url}
            busy={busy}
            onSave={(url) => onSaveUrl(record.id, url)}
          />
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
          {/* The manual escape hatch: the operator applied themselves, so the
              posting becomes an Applications row without the agent ever
              submitting it. No cover-letter gate — they already applied. */}
          <Button
            variant="text"
            size="small"
            disabled={busy}
            onClick={() => onMarkApplied(record.id)}
            title="I applied to this myself — track it on the Applications page"
          >
            I applied
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
  onMoveToFound,
}: {
  record: ScreeningRecord;
  busy: boolean;
  onSaveUrl: (id: string, url: string) => void;
  onMoveToFound: (id: string) => void;
}) {
  return (
    <Paper variant="outlined" sx={{ p: 2 }}>
      <Stack direction="row" spacing={2} sx={{ alignItems: "flex-start" }}>
        <Box sx={{ flex: 1, minWidth: 0 }}>
          <Typography variant="subtitle2">
            {record.company} — {record.role}
          </Typography>
          {!record.url ? (
            <Alert severity="warning" sx={{ mt: 1 }}>
              No URL — this posting cannot be applied to on the next run.
            </Alert>
          ) : null}
          <PostingUrl
            url={record.url}
            busy={busy}
            onSave={(url) => onSaveUrl(record.id, url)}
          />
          <Typography variant="body2" sx={{ color: "text.secondary" }}>
            {record.applyAttempts} attempts
          </Typography>
          {record.applyError ? (
            <Alert severity="warning" sx={{ mt: 1 }}>
              {record.applyError}
            </Alert>
          ) : null}
        </Box>
        <Button
          variant="outlined"
          size="small"
          disabled={busy}
          onClick={() => onMoveToFound(record.id)}
        >
          Move back to Found
        </Button>
      </Stack>
    </Paper>
  );
}

/** The date a row is ordered by, newest first.

 * `postedDate` is the posting's own publication date and the one that matters
 * for "newest", but many boards publish none — so it falls back to when the
 * agent screened it, then to when the record was written. Without the
 * fallbacks every dateless posting would clump at one end regardless of how
 * recently it was found.
 */
export function orderingDate(record: ScreeningRecord): string {
  return record.postedDate || record.screenedDate || record.createdAt || "";
}

/** Newest first. Does not mutate the array it is given. */
export function byDateDesc(records: ScreeningRecord[]): ScreeningRecord[] {
  return [...records].sort((a, b) => {
    const da = orderingDate(a);
    const db = orderingDate(b);
    if (da === db) return 0;
    // ISO-8601 dates sort correctly as strings; a blank sorts last, which is
    // only reachable when a record carries no date of any kind.
    if (!da) return 1;
    if (!db) return -1;
    return da < db ? 1 : -1;
  });
}

/** Chip styling that lets a long label wrap instead of forcing the row wide.
 * MUI fixes a Chip's height and sets `white-space: nowrap` on its label, so a
 * multi-hundred-character value overflows the viewport unless both are undone. */
const WRAPPING_CHIP = {
  maxWidth: "100%",
  height: "auto",
  "& .MuiChip-label": {
    whiteSpace: "normal",
    overflowWrap: "anywhere",
    py: 0.5,
    display: "block",
  },
} as const;

/** A rejected or agent-filtered posting, reviewable and reversible: shows
 * why it was set aside and offers the one way back into the queue. When
 * ``rejectedLabel`` is set the row carries a provenance stamp saying who
 * rejected it — the agent's filter or the operator's own decision. */
function ReviewRow({
  record,
  busy,
  checked,
  onToggle,
  onMoveToApprovals,
  onSaveUrl,
  onDelete,
  rejectedLabel,
}: {
  record: ScreeningRecord;
  busy: boolean;
  checked: boolean;
  onToggle: (id: string) => void;
  onMoveToApprovals: (id: string) => void;
  onSaveUrl: (id: string, url: string) => void;
  onDelete: (id: string) => void;
  rejectedLabel?: string;
}) {
  const active = isCooldownActive(record.cooldownExpires);
  return (
    <Paper variant="outlined" sx={{ p: 2, overflow: "hidden" }}>
      <Stack direction="row" spacing={2} sx={{ alignItems: "flex-start" }}>
        <Checkbox
          checked={checked}
          onChange={() => onToggle(record.id)}
          disabled={busy}
          sx={{ mt: -1, ml: -1 }}
          slotProps={{ input: { "aria-label": `Select ${record.company} ${record.role}` } }}
        />
        <Box sx={{ flex: 1, minWidth: 0 }}>
          <Typography variant="subtitle1" sx={{ overflowWrap: "anywhere" }}>
            {record.company}
          </Typography>
          <Typography
            variant="body2"
            sx={{ color: "text.secondary", overflowWrap: "anywhere" }}
          >
            {record.role}
          </Typography>
          <PostingUrl
            url={record.url}
            busy={busy}
            onSave={(url) => onSaveUrl(record.id, url)}
          />
          {active && record.failingCriterion === "cooldown" ? (
            <Chip
              size="small"
              variant="outlined"
              color="warning"
              label={cooldownBlockLabel(record.cooldownWindow ?? null)}
              sx={{ mt: 0.5 }}
            />
          ) : null}
          {/* A failing criterion is free text the agent writes and runs to
              several hundred characters. A Chip never wraps its label, so an
              unwrapped one pushed the whole page sideways; these let it break
              and grow instead. */}
          <Stack
            direction="row"
            spacing={1}
            sx={{ mt: 0.5, alignItems: "flex-start", flexWrap: "wrap", rowGap: 1 }}
          >
            {rejectedLabel ? (
              <Chip size="small" label={rejectedLabel} sx={{ flexShrink: 0 }} />
            ) : null}
            {record.failingCriterion ? (
              <Chip size="small" label={record.failingCriterion} sx={WRAPPING_CHIP} />
            ) : null}
            {record.reason ? (
              <Typography
                variant="body2"
                sx={{ color: "text.secondary", minWidth: 0, overflowWrap: "anywhere" }}
              >
                {record.reason}
              </Typography>
            ) : null}
          </Stack>
        </Box>
        <Stack spacing={1} sx={{ flexShrink: 0 }}>
          <Button
            variant="outlined"
            size="small"
            disabled={busy}
            onClick={() => onMoveToApprovals(record.id)}
          >
            Move to approvals
          </Button>
          <Button
            variant="text"
            size="small"
            color="error"
            disabled={busy}
            onClick={() => onDelete(record.id)}
            aria-label={`Delete ${record.company} ${record.role}`}
          >
            Delete
          </Button>
        </Stack>
      </Stack>
    </Paper>
  );
}

/** An applied queue item, settled into an application. Read-only here: its
 * record lives on the Applications page, not in this queue. */
function AppliedRow({ record }: { record: ScreeningRecord }) {
  return (
    <Paper variant="outlined" sx={{ p: 2 }}>
      <Typography variant="subtitle2">
        {record.company} — {record.role}
      </Typography>
      {record.url ? (
        <Link href={record.url} target="_blank" rel="noreferrer" variant="body2">
          {record.url}
        </Link>
      ) : null}
      {record.screenedDate ? (
        <Typography variant="body2" sx={{ color: "text.secondary" }}>
          Screened {record.screenedDate}
        </Typography>
      ) : null}
    </Paper>
  );
}

/** One tab body. Inactive panels unmount rather than hide, so a hidden tab's
 * PendingCards never mount — otherwise each would fetch a cover-letter draft
 * the operator cannot see. */
function QueuePanel({
  value,
  index,
  children,
}: {
  value: number;
  index: number;
  children: React.ReactNode;
}) {
  if (value !== index) return null;
  return (
    <Box role="tabpanel" sx={{ mt: 2 }}>
      {children}
    </Box>
  );
}

/** The operator's approval queue, as four tabs: what the agent found and
 * deferred (Found), what is approved and waiting to be applied (Queued),
 * what was set aside and why (Rejected), and what has already settled into
 * tracked applications (Applied, read-only). Counts live in the labels so
 * each queue's size is visible without switching to it; decisions move rows
 * between the in-memory lists so the counts stay right without a refetch. */
export function ApprovalsPage({ onBack }: { onBack: () => void }) {
  const [pending, setPending] = useState<ScreeningRecord[]>([]);
  const [approved, setApproved] = useState<ScreeningRecord[]>([]);
  const [rejected, setRejected] = useState<ScreeningRecord[]>([]);
  const [didNotPass, setDidNotPass] = useState<ScreeningRecord[]>([]);
  const [applied, setApplied] = useState<ScreeningRecord[]>([]);
  const [selected, setSelected] = useState<string[]>([]);
  const [rejectedSelected, setRejectedSelected] = useState<string[]>([]);
  const [confirmDelete, setConfirmDelete] = useState(false);
  const [appliedNotice, setAppliedNotice] = useState("");
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [tab, setTab] = useState(0);

  useEffect(() => {
    let live = true;
    Promise.all([
      listPendingApprovals(),
      listApprovedApplications(),
      listRejectedApprovals(),
      listDidNotPass(),
      listAppliedScreenings(),
    ])
      .then(([p, a, r, d, ap]) => {
        if (!live) return;
        setPending(p);
        setApproved(a);
        setRejected(r);
        setDidNotPass(d);
        setApplied(ap);
      })
      .catch((e) => live && setError(String(e)))
      .finally(() => live && setLoading(false));
    return () => {
      live = false;
    };
  }, []);

  // The Rejected tab merges two sources: the agent's criterion rejections
  // (never queued, empty approval) and the operator's own rejections.
  // De-duplicated by id — the populations are disjoint in practice, but a
  // record must never show twice if that ever changes. didNotPass wins the
  // tie, labelling an overlap as agent-rejected.
  const rejectedRows: ScreeningRecord[] = [];
  const seenIds = new Set<string>();
  for (const r of [...didNotPass, ...rejected]) {
    if (seenIds.has(r.id)) continue;
    seenIds.add(r.id);
    rejectedRows.push(r);
  }
  const agentRejected = new Set(didNotPass.map((r) => r.id));

  const toggle = (id: string) =>
    setSelected((s) => (s.includes(id) ? s.filter((x) => x !== id) : [...s, id]));

  const toggleAll = () =>
    setSelected((s) => (s.length === pending.length ? [] : pending.map((r) => r.id)));

  // The Rejected tab keeps its own selection. Sharing `selected` with Found
  // would carry a selection across a tab switch and delete rows the operator
  // ticked for a different action entirely.
  const toggleRejected = (id: string) =>
    setRejectedSelected((s) =>
      s.includes(id) ? s.filter((x) => x !== id) : [...s, id],
    );

  const toggleAllRejected = () =>
    setRejectedSelected((s) =>
      s.length === rejectedRows.length ? [] : rejectedRows.map((r) => r.id),
    );

  /** Drop ids from whichever rejected list held them, plus the selection. */
  function forgetRejected(ids: string[]) {
    const gone = new Set(ids);
    setRejected((rows) => rows.filter((r) => !gone.has(r.id)));
    setDidNotPass((rows) => rows.filter((r) => !gone.has(r.id)));
    setRejectedSelected((s) => s.filter((x) => !gone.has(x)));
  }

  async function deleteOne(id: string) {
    setBusy(true);
    setError("");
    try {
      await deleteScreening(id);
      forgetRejected([id]);
    } catch (e) {
      setError(String(e));
    } finally {
      setBusy(false);
    }
  }

  async function deleteSelectedRejected() {
    setBusy(true);
    setError("");
    try {
      const { deleted, missing } = await bulkDeleteScreenings(rejectedSelected);
      // A missing id is one another tab already removed: drop it from the list
      // too, or it lingers as a row that no longer exists anywhere.
      forgetRejected([...deleted, ...missing]);
    } catch (e) {
      setError(String(e));
    } finally {
      setBusy(false);
      setConfirmDelete(false);
    }
  }

  async function decide(id: string, approval: "approved" | "rejected") {
    setBusy(true);
    setError("");
    try {
      const updated = await setScreeningApproval(id, approval);
      setPending((rows) => rows.filter((r) => r.id !== id));
      setSelected((s) => s.filter((x) => x !== id));
      // Move the row to the queue it just joined so the tab counts stay
      // correct without a refetch.
      if (approval === "approved") setApproved((rows) => [updated, ...rows]);
      else setRejected((rows) => [updated, ...rows]);
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
      // visible rather than disappearing as if it had been decided. The rest
      // move to the queue they joined so counts stay right without a refetch.
      const moved = pending
        .filter((r) => selected.includes(r.id) && !failed.has(r.id))
        .map((r) => ({ ...r, approval }));
      setPending((rows) =>
        rows.filter((r) => !selected.includes(r.id) || failed.has(r.id)),
      );
      if (approval === "approved") setApproved((rows) => [...moved, ...rows]);
      else setRejected((rows) => [...moved, ...rows]);
      setSelected([]);
      if (failed.size) setError(`${failed.size} could not be updated.`);
    } catch (e) {
      setError(String(e));
    } finally {
      setBusy(false);
    }
  }

  /** The operator applied by hand: create the Applications row, retire the
   * queue item. The row leaves Found because it is no longer a decision the
   * operator owes the agent — it is a tracked application now. */
  async function markApplied(id: string) {
    setBusy(true);
    setError("");
    try {
      await markScreeningApplied(id);
      setPending((rows) => rows.filter((r) => r.id !== id));
      setSelected((sel) => sel.filter((x) => x !== id));
      setAppliedNotice("Added to the Applications page.");
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
      setRejected((rows) => rows.map((r) => (r.id === id ? updated : r)));
      setDidNotPass((rows) => rows.map((r) => (r.id === id ? updated : r)));
    } catch (e) {
      setError(String(e));
    } finally {
      setBusy(false);
    }
  }

  async function moveToFound(id: string) {
    setBusy(true);
    setError("");
    try {
      const updated = await setScreeningApproval(id, "pending");
      setApproved((rows) => rows.filter((r) => r.id !== id));
      setPending((rows) => [updated, ...rows]);
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
      ) : (
        <>
          <Tabs
            value={tab}
            onChange={(_, v: number) => setTab(v)}
            aria-label="Approval queues"
          >
            <Tab label={`Found (${pending.length})`} />
            <Tab label={`Queued (${approved.length})`} />
            <Tab label={`Rejected (${rejectedRows.length})`} />
            <Tab label={`Applied (${applied.length})`} />
          </Tabs>

          <QueuePanel value={tab} index={0}>
            {/* Outside the empty-check: applying the last row empties the list,
                which is exactly when the operator most needs telling where it
                went. */}
            {appliedNotice ? (
              <Alert
                severity="success"
                sx={{ mb: 2 }}
                onClose={() => setAppliedNotice("")}
              >
                {appliedNotice}
              </Alert>
            ) : null}
            {pending.length === 0 ? (
              <Typography variant="body1">Nothing waiting.</Typography>
            ) : (
              <Stack spacing={2}>
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
                {byDateDesc(pending).map((r) => (
                  <PendingCard
                    key={r.id}
                    record={r}
                    checked={selected.includes(r.id)}
                    busy={busy}
                    onToggle={toggle}
                    onDecide={decide}
                    onSaveUrl={saveUrl}
                    onMarkApplied={markApplied}
                  />
                ))}
              </Stack>
            )}
          </QueuePanel>

          <QueuePanel value={tab} index={1}>
            {approved.length === 0 ? (
              <Typography variant="body1">Nothing queued.</Typography>
            ) : (
              <Stack spacing={2}>
                <Typography variant="body2" sx={{ color: "text.secondary" }}>
                  Approved and waiting for the next scheduled run.
                </Typography>
                {approved.map((r) => (
                  <ApprovedRow
                    key={r.id}
                    record={r}
                    busy={busy}
                    onSaveUrl={saveUrl}
                    onMoveToFound={moveToFound}
                  />
                ))}
              </Stack>
            )}
          </QueuePanel>

          <QueuePanel value={tab} index={2}>
            {rejectedRows.length === 0 ? (
              <Typography variant="body1">Nothing rejected.</Typography>
            ) : (
              <Stack spacing={2}>
                <Typography variant="body2" sx={{ color: "text.secondary" }}>
                  Postings set aside by the agent's criteria or by you. You can send
                  either kind back to the queue, or delete them for good.
                </Typography>
                <Stack direction="row" spacing={1} sx={{ alignItems: "center", flexWrap: "wrap" }}>
                  <FormControlLabel
                    control={
                      <Checkbox
                        checked={
                          rejectedSelected.length === rejectedRows.length &&
                          rejectedRows.length > 0
                        }
                        indeterminate={
                          rejectedSelected.length > 0 &&
                          rejectedSelected.length < rejectedRows.length
                        }
                        onChange={toggleAllRejected}
                        disabled={busy}
                        slotProps={{ input: { "aria-label": "Select all rejected" } }}
                      />
                    }
                    label={`Select all (${rejectedRows.length})`}
                  />
                  <Button
                    variant="outlined"
                    size="small"
                    color="error"
                    disabled={busy || rejectedSelected.length === 0}
                    onClick={() => setConfirmDelete(true)}
                  >
                    Delete selected ({rejectedSelected.length})
                  </Button>
                </Stack>
                {rejectedRows.map((r) => (
                  <ReviewRow
                    key={r.id}
                    record={r}
                    busy={busy}
                    checked={rejectedSelected.includes(r.id)}
                    onToggle={toggleRejected}
                    onMoveToApprovals={moveToApprovals}
                    onSaveUrl={saveUrl}
                    onDelete={deleteOne}
                    rejectedLabel={
                      agentRejected.has(r.id) ? "Rejected by agent" : "Rejected by you"
                    }
                  />
                ))}
              </Stack>
            )}
            {/* Deletion is the one action on this page with no way back —
                Move to approvals is reversible, this is not. */}
            <Dialog open={confirmDelete} onClose={() => setConfirmDelete(false)}>
              <DialogTitle>
                Delete {rejectedSelected.length} rejected{" "}
                {rejectedSelected.length === 1 ? "posting" : "postings"}?
              </DialogTitle>
              <DialogContent>
                <DialogContentText>
                  This removes the screening records for good, including the stored
                  posting text. Their companies also stop being in cooldown, so a
                  future run may find and screen these postings again.
                </DialogContentText>
              </DialogContent>
              <DialogActions>
                <Button onClick={() => setConfirmDelete(false)} disabled={busy}>
                  Cancel
                </Button>
                <Button color="error" onClick={deleteSelectedRejected} disabled={busy}>
                  Delete
                </Button>
              </DialogActions>
            </Dialog>
          </QueuePanel>

          <QueuePanel value={tab} index={3}>
            {applied.length === 0 ? (
              <Typography variant="body1">Nothing applied yet.</Typography>
            ) : (
              <Stack spacing={2}>
                <Typography variant="body2" sx={{ color: "text.secondary" }}>
                  These have been applied to — manage them on the Applications page.
                </Typography>
                {applied.map((r) => (
                  <AppliedRow key={r.id} record={r} />
                ))}
              </Stack>
            )}
          </QueuePanel>
        </>
      )}
    </Box>
  );
}
