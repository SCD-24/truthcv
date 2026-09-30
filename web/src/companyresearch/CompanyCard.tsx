import { useState } from "react";
import Alert from "@mui/material/Alert";
import Box from "@mui/material/Box";
import Button from "@mui/material/Button";
import Chip from "@mui/material/Chip";
import Collapse from "@mui/material/Collapse";
import Link from "@mui/material/Link";
import Paper from "@mui/material/Paper";
import Stack from "@mui/material/Stack";
import Typography from "@mui/material/Typography";
import { CLAIM_TYPES } from "../api/types";
import type { CompanyFinding } from "../api/types";
import { safeHref } from "../utils/safeUrl";
import {
  bySourceRank,
  claimRowLabel,
  contradictionKey,
  currentByClaim,
  formatAsOf,
  groupByClaim,
  historyFor,
  liveFindings,
  sourceClassLabel,
} from "./companyresearch.logic";
import type { CompanyGroup } from "./companyresearch.logic";

type Resolution = "accepted" | "rejected";

/** True when any claim row of this company is an open contradiction. */
export function companyNeedsReview(group: CompanyGroup, contested: Set<string>): boolean {
  return groupByClaim(group.findings).some((c) =>
    contested.has(contradictionKey(group.companyKey, c.claimKey)),
  );
}

/** One finding's evidence: value, source class, source link, as-of and who
 * recorded it. A source URL is agent-scraped, so a disallowed scheme
 * (javascript:, …) renders as inert text, never a clickable href. */
function Evidence({ finding }: { finding: CompanyFinding }) {
  const safe = safeHref(finding.sourceUrl);
  const href = safe && /^https?:/i.test(safe) ? safe : null;
  const recorded = finding.observedAt.slice(0, 10);
  return (
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
          href ? (
            <Link
              href={href}
              target="_blank"
              rel="noreferrer noopener"
              variant="body2"
              sx={{ overflowWrap: "anywhere" }}
            >
              {finding.sourceUrl}
            </Link>
          ) : (
            <Typography variant="body2" sx={{ overflowWrap: "anywhere" }}>
              {finding.sourceUrl}
            </Typography>
          )
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
        {" · "}Recorded {recorded} by {finding.recordedBy || "unknown recorder"}
      </Typography>
    </Box>
  );
}

/** A claim row: the current finding with Correct, or — when contested — every
 * contender with Accept/Reject under a warning. */
function ClaimRow({
  group,
  label,
  rowKey,
  isContested,
  current,
  busy,
  onResolve,
  onCorrect,
}: {
  group: CompanyGroup;
  label: string;
  rowKey: string;
  isContested: boolean;
  current: CompanyFinding | undefined;
  busy: boolean;
  onResolve: (id: string, resolution: Resolution) => void;
  onCorrect: (finding: CompanyFinding) => void;
}) {
  return (
    <Box>
      <Typography variant="subtitle2" sx={{ mb: 0.5 }}>
        {label}
      </Typography>
      {isContested ? (
        <Stack spacing={1}>
          <Alert severity="warning">
            Open contradiction for “{group.company}” — sources disagree on this claim. Accept the
            correct finding or reject the wrong one.
          </Alert>
          {bySourceRank(
            liveFindings(group.findings, rowKey).filter(
              (f) => f.sourceClass && f.sourceClass !== "unattributed",
            ),
          ).map((f) => (
            <Paper key={f.id} variant="outlined" sx={{ p: 1.5 }}>
              <Stack direction="row" spacing={2} sx={{ alignItems: "flex-start", flexWrap: "wrap" }}>
                <Evidence finding={f} />
                <Stack direction="row" spacing={1} sx={{ flexShrink: 0 }}>
                  <Button
                    variant="contained"
                    size="small"
                    disabled={busy}
                    onClick={() => onResolve(f.id, "accepted")}
                  >
                    Accept
                  </Button>
                  <Button
                    variant="outlined"
                    size="small"
                    disabled={busy}
                    onClick={() => onResolve(f.id, "rejected")}
                  >
                    Reject
                  </Button>
                </Stack>
              </Stack>
            </Paper>
          ))}
        </Stack>
      ) : current ? (
        <Stack direction="row" spacing={2} sx={{ alignItems: "flex-start", flexWrap: "wrap" }}>
          <Evidence finding={current} />
          {CLAIM_TYPES.some((t) => t.value === current.claim) ? (
            <Button size="small" variant="outlined" onClick={() => onCorrect(current)}>
              Correct
            </Button>
          ) : null}
        </Stack>
      ) : (
        <Typography variant="body2" sx={{ color: "text.secondary" }}>
          No current value — every finding is rejected or superseded.
        </Typography>
      )}
    </Box>
  );
}

/** One company: header with counts and review state, a row per claim, and a
 * collapsed History of superseded and rejected findings. */
export function CompanyCard({
  group,
  contested,
  busy,
  onResolve,
  onCorrect,
}: {
  group: CompanyGroup;
  contested: Set<string>;
  busy: boolean;
  onResolve: (id: string, resolution: Resolution) => void;
  onCorrect: (finding: CompanyFinding) => void;
}) {
  const [open, setOpen] = useState(false);
  const current = currentByClaim(group.findings);
  const history = historyFor(group.findings);
  const needsReview = companyNeedsReview(group, contested);
  const historyId = `history-${group.companyKey.replace(/\W+/g, "-")}`;

  return (
    <Paper variant="outlined" component="section" sx={{ p: 2 }} aria-label={group.company}>
      <Stack direction="row" spacing={1.5} sx={{ alignItems: "center", flexWrap: "wrap", mb: 1.5 }}>
        <Typography variant="h6" component="h2">
          {group.company}
        </Typography>
        <Typography variant="body2" sx={{ color: "text.secondary" }}>
          {group.findings.length} {group.findings.length === 1 ? "finding" : "findings"}
        </Typography>
        {needsReview ? <Chip size="small" color="warning" label="Needs review" /> : null}
      </Stack>
      <Stack spacing={2}>
        {groupByClaim(group.findings).map((c) => (
          <ClaimRow
            key={c.claimKey}
            group={group}
            label={c.label}
            rowKey={c.claimKey}
            isContested={contested.has(contradictionKey(group.companyKey, c.claimKey))}
            current={current.get(c.claimKey)}
            busy={busy}
            onResolve={onResolve}
            onCorrect={onCorrect}
          />
        ))}
      </Stack>
      {history.length > 0 ? (
        <Box sx={{ mt: 2 }}>
          <Button
            size="small"
            aria-expanded={open}
            aria-controls={historyId}
            onClick={() => setOpen((v) => !v)}
          >
            History ({history.length})
          </Button>
          <Collapse in={open} unmountOnExit id={historyId}>
            <Stack spacing={1} sx={{ mt: 1 }}>
              {history.map((f) => (
                <Paper key={f.id} variant="outlined" sx={{ p: 1.5 }}>
                  <Typography variant="caption" sx={{ color: "text.secondary" }}>
                    {claimRowLabel(f)}
                    {" · "}
                    {f.resolution === "rejected" ? "Rejected" : "Superseded"}
                    {f.resolvedAt ? ` ${f.resolvedAt.slice(0, 10)}` : ""}
                  </Typography>
                  <Evidence finding={f} />
                  {f.resolutionNote ? (
                    <Typography variant="body2" sx={{ mt: 0.5 }}>
                      Note: {f.resolutionNote}
                    </Typography>
                  ) : null}
                </Paper>
              ))}
            </Stack>
          </Collapse>
        </Box>
      ) : null}
    </Paper>
  );
}
