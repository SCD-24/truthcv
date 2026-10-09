import { useEffect, useMemo, useState } from "react";
import Box from "@mui/material/Box";
import Stack from "@mui/material/Stack";
import Button from "@mui/material/Button";
import AddIcon from "@mui/icons-material/Add";
import Alert from "@mui/material/Alert";
import Typography from "@mui/material/Typography";
import CircularProgress from "@mui/material/CircularProgress";
import TextField from "@mui/material/TextField";
import ToggleButton from "@mui/material/ToggleButton";
import {
  createCompanyFinding,
  listCompanyFindings,
  listContradictions,
  resolveCompanyFinding,
} from "../api/client";
import type { CompanyFinding } from "../api/types";
import { CompanyCard, companyNeedsReview } from "./CompanyCard";
import { FindingDialog } from "./FindingDialog";
import type { FindingDraft } from "./FindingDialog";
import {
  filterCompanies,
  groupFindingsByCompany,
  knownCompanies,
  openContradictionKeys,
} from "./companyresearch.logic";

/** Which finding the dialog is open for: none (closed), a new one, or a
 * correction of an existing one. */
type DialogState = null | { finding?: CompanyFinding };

/**
 * The Company Research page — a searchable list with one card per company,
 * each showing the current sourced, dated value per claim. Sources that
 * disagree on a claim surface as an open contradiction the operator resolves
 * by accepting or rejecting a finding. Findings are immutable: adding and
 * correcting both record a new finding in a dialog; a correction supersedes
 * the old one.
 */
export function CompanyResearchPage() {
  const [findings, setFindings] = useState<CompanyFinding[]>([]);
  const [contested, setContested] = useState<Set<string>>(new Set());
  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [actionError, setActionError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [query, setQuery] = useState("");
  const [needsReviewOnly, setNeedsReviewOnly] = useState(false);
  const [dialog, setDialog] = useState<DialogState>(null);

  async function load() {
    const [rows, groups] = await Promise.all([listCompanyFindings(), listContradictions()]);
    setFindings(rows);
    setContested(openContradictionKeys(groups));
  }

  useEffect(() => {
    let alive = true;
    load()
      .catch((e) => {
        if (alive) setLoadError(e instanceof Error ? e.message : "Couldn't load company research.");
      })
      .finally(() => {
        if (alive) setLoading(false);
      });
    return () => {
      alive = false;
    };
  }, []);

  /** Accept or reject a finding, then refresh so the contradiction clears. */
  async function handleResolve(id: string, resolution: "accepted" | "rejected") {
    setBusy(true);
    setActionError(null);
    try {
      await resolveCompanyFinding(id, resolution);
    } catch (e) {
      setActionError(e instanceof Error ? e.message : "Couldn't record your decision.");
      setBusy(false);
      return;
    }
    try {
      await load();
      setLoadError(null);
    } catch (e) {
      setLoadError(e instanceof Error ? e.message : "Couldn't load company research.");
    } finally {
      setBusy(false);
    }
  }

  /** Record a finding (new or superseding) and refresh. A create error
   * propagates to the dialog; a refresh error is a load error. */
  async function handleSubmit(draft: FindingDraft) {
    await createCompanyFinding(draft);
    try {
      await load();
      setLoadError(null);
    } catch (e) {
      setLoadError(e instanceof Error ? e.message : "Couldn't load company research.");
    }
  }

  const all = useMemo(() => groupFindingsByCompany(findings), [findings]);
  const names = useMemo(() => knownCompanies(all), [all]);
  const matching = filterCompanies(all, query);
  const visible = needsReviewOnly
    ? matching.filter((g) => companyNeedsReview(g, contested))
    : matching;
  const filtering = query.trim() !== "" || needsReviewOnly;

  let body;
  if (loading) {
    body = (
      <Stack direction="row" spacing={2} sx={{ py: 6, justifyContent: "center" }}>
        <CircularProgress size={20} sx={{ color: "var(--attest)" }} />
        <Typography color="text.secondary">Loading company research…</Typography>
      </Stack>
    );
  } else if (loadError) {
    body = null;
  } else if (all.length === 0) {
    body = (
      <Stack spacing={2} sx={{ py: 6, alignItems: "center" }}>
        <Typography color="text.secondary">No company findings recorded yet.</Typography>
        <Button variant="outlined" onClick={() => setDialog({})}>
          Add the first finding
        </Button>
      </Stack>
    );
  } else if (visible.length === 0 && filtering) {
    body = (
      <Typography color="text.secondary" sx={{ py: 6, textAlign: "center" }}>
        No companies match your search or filter.
      </Typography>
    );
  } else {
    body = (
      <Stack spacing={2}>
        {visible.map((group) => (
          <CompanyCard
            key={group.companyKey}
            group={group}
            contested={contested}
            busy={busy}
            onResolve={handleResolve}
            onCorrect={(finding) => setDialog({ finding })}
          />
        ))}
      </Stack>
    );
  }

  return (
    <Box className="company-research-page" aria-labelledby="company-research-title">
      <Stack
        direction="row"
        sx={{ mb: 3, alignItems: "flex-start", justifyContent: "space-between", gap: 2 }}
      >
        <Box>
          <Typography
            variant="overline"
            className="company-research__eyebrow"
            sx={{ display: "block" }}
          >
            Sourced &amp; dated
          </Typography>
          <Typography id="company-research-title" variant="h4" component="h1">
            Company Research
          </Typography>
        </Box>
      </Stack>

      <Stack
        direction="row"
        spacing={2}
        sx={{ mb: 3, alignItems: "center", flexWrap: "wrap", rowGap: 1 }}
      >
        <TextField
          size="small"
          type="search"
          label="Search companies"
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          sx={{ flex: 1, minWidth: 220 }}
        />
        <ToggleButton
          value="needs-review"
          size="small"
          selected={needsReviewOnly}
          aria-pressed={needsReviewOnly}
          onChange={() => setNeedsReviewOnly((v) => !v)}
        >
          Needs review
        </ToggleButton>
        <Button variant="contained" startIcon={<AddIcon />} onClick={() => setDialog({})}>
          Add finding
        </Button>
      </Stack>

      {loadError && (
        <Alert
          severity="error"
          sx={{ mb: 2 }}
          action={
            <Button
              color="inherit"
              size="small"
              onClick={() => {
                setLoadError(null);
                setLoading(true);
                load()
                  .catch((e) =>
                    setLoadError(
                      e instanceof Error ? e.message : "Couldn't load company research.",
                    ),
                  )
                  .finally(() => setLoading(false));
              }}
            >
              Retry
            </Button>
          }
        >
          {loadError}
        </Alert>
      )}
      {actionError && (
        <Alert severity="error" sx={{ mb: 2 }} onClose={() => setActionError(null)}>
          {actionError}
        </Alert>
      )}

      {body}

      {dialog ? (
        <FindingDialog
          key={dialog.finding?.id ?? "new"}
          finding={dialog.finding}
          companies={names}
          onClose={() => setDialog(null)}
          onSubmit={handleSubmit}
        />
      ) : null}
    </Box>
  );
}
