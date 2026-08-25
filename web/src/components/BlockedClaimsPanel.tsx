import Alert from "@mui/material/Alert";
import AlertTitle from "@mui/material/AlertTitle";
import Button from "@mui/material/Button";
import type { BlockedClaim, RenderApprovals } from "../api/types";
import { ButtonSpinner } from "./ButtonSpinner";
import "../styles/step.css";

export type Decision = "approve" | "deny";

/** Build render/generation-scoped approvals from the user's per-claim choices. */
export function approvalsFrom(
  claims: BlockedClaim[],
  decisions: Record<string, Decision>,
): RenderApprovals {
  return {
    approvedClaimIds: claims
      .filter((c) => decisions[c.claimId] === "approve")
      .map((c) => c.claimId),
    deniedClaimIds: claims
      .filter((c) => decisions[c.claimId] === "deny")
      .map((c) => c.claimId),
  };
}

/** The blocked-claims approve/deny panel + "Re-check & continue" (ported from
 * DownloadStep). Reused for both the CV render and the cover letter. */
export function BlockedClaimsPanel({
  claims,
  decisions,
  onDecide,
  onRecheck,
  busy,
  ariaLabel,
}: {
  claims: BlockedClaim[];
  decisions: Record<string, Decision>;
  onDecide: (claimId: string, choice: Decision) => void;
  onRecheck: () => void;
  busy: boolean;
  ariaLabel: string;
}) {
  const allDecided = claims.every((c) => decisions[c.claimId]);
  return (
    <div className="claims" role="group" aria-label={ariaLabel}>
      <Alert severity="error" className="claims__alert" sx={{ mb: 2 }}>
        <AlertTitle>
          Blocked: {claims.length}{" "}
          {claims.length === 1 ? "claim isn't" : "claims aren't"} in your truth
          file
        </AlertTitle>
        Statements were made that couldn&apos;t be traced back to your truth
        file. Nothing ships until every one is resolved below.
      </Alert>
      <p className="claims__lede">
        Approve a claim to confirm it&apos;s a true fact about you (it&apos;s
        allowed for this document only — your truth file is never changed), or
        deny it to leave it out.
      </p>
      {claims.map((c) => {
        const choice = decisions[c.claimId];
        return (
          <div className="claim" key={c.claimId} data-choice={choice ?? ""}>
            <p className="claim__text">{c.text}</p>
            {c.tokens.length > 0 && (
              <p className="claim__tokens">
                Couldn&apos;t trace:{" "}
                {c.tokens.map((t) => (
                  <span className="claim__token" key={t}>
                    {t}
                  </span>
                ))}
              </p>
            )}
            <div className="claim__actions">
              <button
                type="button"
                className="claim__btn claim__btn--approve"
                data-active={choice === "approve"}
                aria-pressed={choice === "approve"}
                onClick={() => onDecide(c.claimId, "approve")}
              >
                Approve
              </button>
              <button
                type="button"
                className="claim__btn claim__btn--deny"
                data-active={choice === "deny"}
                aria-pressed={choice === "deny"}
                onClick={() => onDecide(c.claimId, "deny")}
              >
                Deny
              </button>
            </div>
          </div>
        );
      })}
      <Button
        variant="contained"
        disabled={busy || !allDecided}
        onClick={onRecheck}
      >
        {busy && <ButtonSpinner />}
        {busy
          ? "Re-checking…"
          : allDecided
            ? "Re-check & continue"
            : "Decide every claim to continue"}
      </Button>
    </div>
  );
}
