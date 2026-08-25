import { useEffect, useState } from "react";
import type { FormEvent } from "react";
import Box from "@mui/material/Box";
import Stack from "@mui/material/Stack";
import Button from "@mui/material/Button";
import ArrowBackIcon from "@mui/icons-material/ArrowBack";
import Alert from "@mui/material/Alert";
import Typography from "@mui/material/Typography";
import CircularProgress from "@mui/material/CircularProgress";
import Chip from "@mui/material/Chip";
import Link from "@mui/material/Link";
import Paper from "@mui/material/Paper";
import TextField from "@mui/material/TextField";
import MenuItem from "@mui/material/MenuItem";
import {
  createCompanyFinding,
  listCompanyFindings,
  listContradictions,
  resolveCompanyFinding,
} from "../api/client";
import type { CompanyFinding, ContradictionGroup } from "../api/types";

/** Source classes, strongest evidence first. The select is populated from this
 * list in order, and the ranking below is just its index. */
export const SOURCE_CLASSES = [
  "audited_accounts",
  "regulatory_filing",
  "listed_bond_price",
  "company_statement",
  "press",
  "review_site",
  "unattributed",
] as const;

/** Strength rank of a source class: lower is stronger. An unknown class is
 * ranked below every known one, so it always sorts last. */
export function sourceRank(sourceClass: string): number {
  const i = (SOURCE_CLASSES as readonly string[]).indexOf(sourceClass);
  return i === -1 ? SOURCE_CLASSES.length : i;
}

/** Human wording for a source class — underscores are just storage. */
function sourceClassLabel(sourceClass: string): string {
  return sourceClass ? sourceClass.replace(/_/g, " ") : "unattributed";
}

/** The as-of date to show for a finding. Empty means the source date is
 * unknown — render the literal "unknown", never blank and never observedAt. */
export function formatAsOf(finding: CompanyFinding): string {
  return finding.asOf.trim() ? finding.asOf : "unknown";
}

/** One company and the findings recorded against it, in the order given. */
export interface CompanyGroup {
  company: string;
  findings: CompanyFinding[];
}

/** Group findings by company, preserving first-seen order of both companies
 * and the findings within each. Pure — no DOM, unit-testable directly. */
export function groupFindingsByCompany(findings: CompanyFinding[]): CompanyGroup[] {
  const map = new Map<string, CompanyFinding[]>();
  for (const finding of findings) {
    const list = map.get(finding.company);
    if (list) list.push(finding);
    else map.set(finding.company, [finding]);
  }
  return Array.from(map, ([company, grouped]) => ({ company, findings: grouped }));
}

/** One claim and the findings that cite a value for it. */
export interface ClaimGroup {
  claim: string;
  findings: CompanyFinding[];
}

/** Group findings by claim, preserving first-seen order. Pure. */
export function groupByClaim(findings: CompanyFinding[]): ClaimGroup[] {
  const map = new Map<string, CompanyFinding[]>();
  for (const finding of findings) {
    const list = map.get(finding.claim);
    if (list) list.push(finding);
    else map.set(finding.claim, [finding]);
  }
  return Array.from(map, ([claim, grouped]) => ({ claim, findings: grouped }));
}

/** Findings sorted strongest source first; does not mutate its argument. */
export function bySourceRank(findings: CompanyFinding[]): CompanyFinding[] {
  return [...findings].sort((a, b) => sourceRank(a.sourceClass) - sourceRank(b.sourceClass));
}

/** The key identifying a (company, claim) pair. The claim string alone is not
 * unique across companies, so a contradiction is keyed on both. */
export function contradictionKey(company: string, claim: string): string {
  return `${company}\u0000${claim}`;
}

/** Every (company, claim) pair the backend reports as an open contradiction,
 * as a set of keys for O(1) lookup while rendering. Pure. */
export function openContradictionKeys(groups: ContradictionGroup[]): Set<string> {
  const keys = new Set<string>();
  for (const group of groups) {
    for (const finding of group.findings) {
      keys.add(contradictionKey(finding.company, group.claim));
    }
  }
  return keys;
}

/** One finding's evidence: its value, source class, a link to the source, and
 * the as-of date. In an open contradiction it also carries Accept/Reject —
 * the only mutations allowed; the factual fields are never editable here. */
function FindingRow({
  finding,
  contested,
  busy,
  onResolve,
}: {
  finding: CompanyFinding;
  contested: boolean;
  busy: boolean;
  onResolve: (id: string, resolution: "accepted" | "rejected") => void;
}) {
  return (
    <Paper variant="outlined" sx={{ p: 1.5 }}>
      <Stack direction="row" spacing={2} sx={{ alignItems: "flex-start", flexWrap: "wrap" }}>
        <Box sx={{ flex: 1, minWidth: 0 }}>
          <Typography variant="body1" sx={{ overflowWrap: "anywhere" }}>
            {finding.value}
          </Typography>
          <Stack
            direction="row"
            spacing={1}
            sx={{ mt: 0.5, alignItems: "center", flexWrap: "wrap", rowGap: 0.5 }}
          >
            <Chip size="small" label={sourceClassLabel(finding.sourceClass)} />
            {finding.sourceUrl ? (
              <Link
                href={finding.sourceUrl}
                target="_blank"
                rel="noreferrer noopener"
                variant="body2"
                sx={{ overflowWrap: "anywhere" }}
              >
                {finding.sourceUrl}
              </Link>
            ) : (
              <Typography variant="body2" sx={{ color: "text.secondary" }}>
                no source link
              </Typography>
            )}
          </Stack>
          <Typography variant="body2" sx={{ color: "text.secondary", mt: 0.5 }}>
            As of{" "}
            <Box component="span" sx={{ color: "text.primary" }}>
              {formatAsOf(finding)}
            </Box>
          </Typography>
          {finding.resolution ? (
            <Chip
              size="small"
              variant="outlined"
              color={finding.resolution === "accepted" ? "success" : "default"}
              label={finding.resolution}
              sx={{ mt: 0.5 }}
            />
          ) : null}
        </Box>
        {contested ? (
          <Stack direction="row" spacing={1} sx={{ flexShrink: 0 }}>
            <Button
              variant="contained"
              size="small"
              disabled={busy}
              onClick={() => onResolve(finding.id, "accepted")}
            >
              Accept
            </Button>
            <Button
              variant="outlined"
              size="small"
              disabled={busy}
              onClick={() => onResolve(finding.id, "rejected")}
            >
              Reject
            </Button>
          </Stack>
        ) : null}
      </Stack>
    </Paper>
  );
}

/** One claim's findings. When the pair is an open contradiction, every finding
 * for it renders adjacent, strongest source first, under a warning; otherwise
 * they list plainly. */
function ClaimSection({
  company,
  group,
  contested,
  busy,
  onResolve,
}: {
  company: string;
  group: ClaimGroup;
  contested: boolean;
  busy: boolean;
  onResolve: (id: string, resolution: "accepted" | "rejected") => void;
}) {
  const ordered = bySourceRank(group.findings);
  const rows = (
    <Stack spacing={1}>
      {ordered.map((finding) => (
        <FindingRow
          key={finding.id}
          finding={finding}
          contested={contested}
          busy={busy}
          onResolve={onResolve}
        />
      ))}
    </Stack>
  );

  return (
    <Box>
      <Typography variant="subtitle2" sx={{ mb: 0.5 }}>
        {group.claim}
      </Typography>
      {contested ? (
        <Alert severity="warning" sx={{ mb: 1 }}>
          Open contradiction for “{company}” — sources disagree on this claim.
          Accept the correct finding or reject the wrong one.
        </Alert>
      ) : null}
      {rows}
    </Box>
  );
}

/** Record a new operator-sourced finding. A source URL is mandatory — a
 * finding with nowhere to trace it back to is refused before it is sent. The
 * factual fields are write-once, so there is no edit form anywhere else. */
function AddFindingForm({
  onCreate,
}: {
  onCreate: (body: {
    company: string;
    claim: string;
    value: string;
    sourceUrl: string;
    sourceClass: string;
    asOf?: string;
    note?: string;
  }) => Promise<void>;
}) {
  const [company, setCompany] = useState("");
  const [claim, setClaim] = useState("");
  const [value, setValue] = useState("");
  const [sourceUrl, setSourceUrl] = useState("");
  const [sourceClass, setSourceClass] = useState<string>(SOURCE_CLASSES[0]);
  const [asOf, setAsOf] = useState("");
  const [note, setNote] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  async function submit(e: FormEvent) {
    e.preventDefault();
    if (!sourceUrl.trim()) {
      setError("A source URL is required — every finding must cite where it came from.");
      return;
    }
    setBusy(true);
    setError("");
    try {
      await onCreate({
        company,
        claim,
        value,
        sourceUrl,
        sourceClass,
        asOf: asOf || undefined,
        note: note || undefined,
      });
      setCompany("");
      setClaim("");
      setValue("");
      setSourceUrl("");
      setSourceClass(SOURCE_CLASSES[0]);
      setAsOf("");
      setNote("");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Couldn't record the finding.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <Paper variant="outlined" sx={{ p: 2 }} component="form" onSubmit={submit}>
      <Typography variant="subtitle1" sx={{ mb: 1.5 }}>
        Record a finding
      </Typography>
      {error ? (
        <Alert severity="error" sx={{ mb: 2 }}>
          {error}
        </Alert>
      ) : null}
      <Stack spacing={2}>
        <TextField
          label="Company"
          value={company}
          onChange={(e) => setCompany(e.target.value)}
        />
        <TextField label="Claim" value={claim} onChange={(e) => setClaim(e.target.value)} />
        <TextField label="Value" value={value} onChange={(e) => setValue(e.target.value)} />
        <TextField
          label="Source URL"
          value={sourceUrl}
          onChange={(e) => setSourceUrl(e.target.value)}
          placeholder="https://..."
          helperText="Required — every finding must cite where it came from."
        />
        <TextField
          select
          label="Source class"
          value={sourceClass}
          onChange={(e) => setSourceClass(e.target.value)}
        >
          {SOURCE_CLASSES.map((cls) => (
            <MenuItem key={cls} value={cls}>
              {sourceClassLabel(cls)}
            </MenuItem>
          ))}
        </TextField>
        <TextField
          label="As-of date"
          value={asOf}
          onChange={(e) => setAsOf(e.target.value)}
          placeholder="YYYY-MM-DD"
          helperText="Leave empty when unknown — do not guess."
        />
        <TextField
          label="Note"
          value={note}
          onChange={(e) => setNote(e.target.value)}
          multiline
          minRows={2}
        />
        <Box>
          <Button type="submit" variant="contained" disabled={busy}>
            Record finding
          </Button>
        </Box>
      </Stack>
    </Paper>
  );
}

/**
 * The Company Research page — sourced, dated findings the agent and operators
 * record about employers, grouped by company and then by claim. Sources that
 * disagree on a claim surface as an open contradiction the operator resolves
 * by accepting or rejecting a finding. Findings are immutable once written:
 * only the resolution changes here. `onBack` returns to the previous page.
 */
export function CompanyResearchPage({ onBack }: { onBack?: () => void }) {
  const [findings, setFindings] = useState<CompanyFinding[]>([]);
  const [contested, setContested] = useState<Set<string>>(new Set());
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function load() {
    const [rows, groups] = await Promise.all([listCompanyFindings(), listContradictions()]);
    setFindings(rows);
    setContested(openContradictionKeys(groups));
  }

  useEffect(() => {
    let alive = true;
    load()
      .catch((e) => {
        if (alive) setError(e instanceof Error ? e.message : "Couldn't load company research.");
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
    setError(null);
    try {
      await resolveCompanyFinding(id, resolution);
      await load();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Couldn't record your decision.");
    } finally {
      setBusy(false);
    }
  }

  /** Record a new finding and refresh the list. Errors propagate to the form. */
  async function handleCreate(body: {
    company: string;
    claim: string;
    value: string;
    sourceUrl: string;
    sourceClass: string;
    asOf?: string;
    note?: string;
  }) {
    await createCompanyFinding(body);
    await load();
  }

  const companies = groupFindingsByCompany(findings);

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
        {onBack ? (
          <Button variant="text" startIcon={<ArrowBackIcon />} onClick={onBack}>
            Back
          </Button>
        ) : null}
      </Stack>

      {error && (
        <Alert severity="error" sx={{ mb: 2 }}>
          {error}
        </Alert>
      )}

      <Stack spacing={3}>
        <AddFindingForm onCreate={handleCreate} />

        {loading ? (
          <Stack direction="row" spacing={2} sx={{ py: 6, justifyContent: "center" }}>
            <CircularProgress size={20} sx={{ color: "var(--attest)" }} />
            <Typography color="text.secondary">Loading company research…</Typography>
          </Stack>
        ) : companies.length === 0 ? (
          <Typography color="text.secondary" sx={{ py: 6, textAlign: "center" }}>
            No company findings recorded yet.
          </Typography>
        ) : (
          <Stack spacing={3}>
            {companies.map(({ company, findings: companyFindings }) => (
              <Box key={company}>
                <Typography variant="h6" component="h2" sx={{ mb: 1 }}>
                  {company}
                </Typography>
                <Stack spacing={2}>
                  {groupByClaim(companyFindings).map((group) => (
                    <ClaimSection
                      key={group.claim}
                      company={company}
                      group={group}
                      contested={contested.has(contradictionKey(company, group.claim))}
                      busy={busy}
                      onResolve={handleResolve}
                    />
                  ))}
                </Stack>
              </Box>
            ))}
          </Stack>
        )}
      </Stack>
    </Box>
  );
}
