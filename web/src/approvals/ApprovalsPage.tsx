import { useEffect, useState } from "react";
import Alert from "@mui/material/Alert";
import Box from "@mui/material/Box";
import Button from "@mui/material/Button";
import Checkbox from "@mui/material/Checkbox";
import Chip from "@mui/material/Chip";
import CircularProgress from "@mui/material/CircularProgress";
import Divider from "@mui/material/Divider";
import FormControlLabel from "@mui/material/FormControlLabel";
import Link from "@mui/material/Link";
import Paper from "@mui/material/Paper";
import Stack from "@mui/material/Stack";
import Typography from "@mui/material/Typography";
import ArrowBackIcon from "@mui/icons-material/ArrowBack";
import {
  bulkSetApproval,
  listApprovedApplications,
  listPendingApprovals,
  setCompanyApproval,
  setScreeningApproval,
} from "../api/client";
import type { ScreeningRecord } from "../api/types";

/** One posting waiting on the operator: what the agent found, why it stopped,
 * and the two decisions available. */
function PendingCard({
  record,
  checked,
  busy,
  onToggle,
  onDecide,
  onApproveCompany,
}: {
  record: ScreeningRecord;
  checked: boolean;
  busy: boolean;
  onToggle: (id: string) => void;
  onDecide: (id: string, approval: "approved" | "rejected") => void;
  onApproveCompany: (company: string) => void;
}) {
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
          ) : null}
          <Stack direction="row" spacing={1} sx={{ mt: 1, alignItems: "center" }}>
            {record.failingCriterion ? (
              <Chip size="small" label={record.failingCriterion} />
            ) : null}
            <Typography variant="body2">{record.reason}</Typography>
          </Stack>
        </Box>
        <Stack spacing={1}>
          <Button
            variant="contained"
            size="small"
            disabled={busy}
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
          <Button
            size="small"
            disabled={busy || !record.company}
            onClick={() => onApproveCompany(record.company)}
            title="Clears deferral blockers for any role here. Roles are still screened."
          >
            Approve company
          </Button>
        </Stack>
      </Stack>
    </Paper>
  );
}

/** An approved item that has not been applied to yet. Its attempt count and
 * last error are the only signal that a posting is failing every run, which is
 * the manual drain for the retry-forever policy. */
function ApprovedRow({ record }: { record: ScreeningRecord }) {
  return (
    <Paper variant="outlined" sx={{ p: 2 }}>
      <Typography variant="subtitle2">
        {record.company} — {record.role}
      </Typography>
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

/** The operator's approval queue: postings the agent deferred, and the ones
 * already approved but not yet applied to. */
export function ApprovalsPage({ onBack }: { onBack: () => void }) {
  const [pending, setPending] = useState<ScreeningRecord[]>([]);
  const [approved, setApproved] = useState<ScreeningRecord[]>([]);
  const [selected, setSelected] = useState<string[]>([]);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  useEffect(() => {
    let live = true;
    Promise.all([listPendingApprovals(), listApprovedApplications()])
      .then(([p, a]) => {
        if (!live) return;
        setPending(p);
        setApproved(a);
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

  async function approveCompany(company: string) {
    setBusy(true);
    setError("");
    try {
      await setCompanyApproval(company, true);
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
      ) : pending.length === 0 && approved.length === 0 ? (
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
                  onApproveCompany={approveCompany}
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
                <ApprovedRow key={r.id} record={r} />
              ))}
            </>
          ) : null}
        </Stack>
      )}
    </Box>
  );
}
