import { useEffect, useState } from "react";
import Box from "@mui/material/Box";
import Button from "@mui/material/Button";
import Alert from "@mui/material/Alert";
import AlertTitle from "@mui/material/AlertTitle";
import Typography from "@mui/material/Typography";
import type { StepProps } from "../wizard/steps";
import { useWizard } from "../wizard/store";
import { generateCoverLetter, render as renderCv } from "../api/client";
import { DocumentEditor } from "./DocumentEditor";
import "../styles/step.css";

const TONES = ["Professional", "Warm", "Concise"] as const;
const LENGTHS = ["Short", "Standard"] as const;

export function DownloadStep({ onBack }: StepProps) {
  const {
    render: result,
    setRender,
    coverLetter,
    setCoverLetter,
    run,
    loading,
    error,
  } = useWizard();

  const [tone, setTone] = useState<(typeof TONES)[number]>("Professional");
  const [length, setLength] = useState<(typeof LENGTHS)[number]>("Standard");
  const [letterBusy, setLetterBusy] = useState(false);
  const [letterError, setLetterError] = useState<string | null>(null);
  // Per-claim approve/deny decisions, keyed by claimId. Render-scoped only —
  // approving never writes to the truth file, so the same truth can back many
  // tailored CVs.
  const [decisions, setDecisions] = useState<Record<string, "approve" | "deny">>({});

  // Run the guardrail + ATS review and render as soon as we arrive.
  useEffect(() => {
    run(async () => {
      const r = await renderCv();
      setRender(r);
      return true;
    });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const blocked = result?.blocked === true;
  const claims = result?.blockedClaims ?? [];
  const allDecided = claims.every((c) => decisions[c.claimId]);

  const decide = (claimId: string, choice: "approve" | "deny") =>
    setDecisions((d) => ({ ...d, [claimId]: choice }));

  // Re-render with the decisions applied. Approved claims are allowed for this
  // render; denied claims are dropped from the CV. Any still-undecided claim
  // will simply block again, so the user can resolve them in another pass.
  const recheck = () =>
    run(async () => {
      const approvedClaimIds = claims
        .filter((c) => decisions[c.claimId] === "approve")
        .map((c) => c.claimId);
      const deniedClaimIds = claims
        .filter((c) => decisions[c.claimId] === "deny")
        .map((c) => c.claimId);
      setRender(await renderCv({ approvedClaimIds, deniedClaimIds }));
      return true;
    });

  const makeLetter = async () => {
    setLetterBusy(true);
    setLetterError(null);
    try {
      const r = await generateCoverLetter(tone.toLowerCase(), length.toLowerCase());
      setCoverLetter(r);
    } catch (e) {
      setLetterError(e instanceof Error ? e.message : "Couldn't write the letter.");
    } finally {
      setLetterBusy(false);
    }
  };

  const letterBlocked = coverLetter?.blocked === true;

  return (
    <section>
      <div className="stage__head">
        <Typography variant="overline" className="eyebrow">Step 5 of 5</Typography>
        <h1 className="stage__title">
          {blocked ? "One more check before you download" : "A CV you can stand behind"}
        </h1>
        <p className="stage__lede">
          {blocked
            ? "The guardrail found claims it couldn't trace back to your truth file. Nothing ships until every fact checks out."
            : "We checked every fact against your truth file and ran an ATS review. Download it as PDF or DOCX."}
        </p>
      </div>

      {loading && (
        <Typography variant="body2" className="busy" sx={{ color: "text.secondary" }}>
          Checking every fact against your truth file…
        </Typography>
      )}
      {error && (
        <Alert severity="error" sx={{ mb: 3 }}>
          {error}
        </Alert>
      )}

      {blocked && result && (
        <div className="claims" role="group" aria-label="Claims to approve or deny">
          <p className="claims__lede">
            Approve a claim to confirm it&apos;s a true fact about you (it&apos;s
            allowed for this CV only — your truth file is never changed), or deny
            it to leave it out.
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
                    onClick={() => decide(c.claimId, "approve")}
                  >
                    Approve
                  </button>
                  <button
                    type="button"
                    className="claim__btn claim__btn--deny"
                    data-active={choice === "deny"}
                    aria-pressed={choice === "deny"}
                    onClick={() => decide(c.claimId, "deny")}
                  >
                    Deny
                  </button>
                </div>
              </div>
            );
          })}
          <Button
            variant="contained"
            disabled={loading || !allDecided}
            onClick={recheck}
          >
            {loading
              ? "Re-checking…"
              : allDecided
                ? "Re-check & continue"
                : "Decide every claim to continue"}
          </Button>
        </div>
      )}

      {!blocked && result && result.atsWarnings.length > 0 && (
        <Alert severity="warning" sx={{ mb: 3 }}>
          <AlertTitle>ATS review</AlertTitle>
          <ul className="notice__list">
            {result.atsWarnings.map((w) => (
              <li key={w.code}>{w.message}</li>
            ))}
          </ul>
        </Alert>
      )}

      {!blocked && result && (
        <Box className="downloads" sx={{ display: "flex", gap: 2, flexWrap: "wrap" }}>
          {result.pdfUrl && (
            <Button variant="outlined" component="a" href={result.pdfUrl} download>
              Download PDF
            </Button>
          )}
          {result.docxUrl && (
            <Button variant="outlined" component="a" href={result.docxUrl} download>
              Download DOCX
            </Button>
          )}
        </Box>
      )}

      {!blocked && result && (
        <DocumentEditor kind="cv" initial={result.html ?? ""} />
      )}

      {!blocked && result && (
        <section className="coverletter" aria-labelledby="coverletter-title">
          <h2 id="coverletter-title" className="coverletter__title">
            Also write a cover letter
          </h2>
          <p className="coverletter__lede">
            Same rule applies — every fact is checked against your truth file.
          </p>

          <div className="choice-group">
            <span className="field__label">Tone</span>
            <div className="choice-row">
              {TONES.map((t) => (
                <button
                  key={t}
                  type="button"
                  className="choice__btn"
                  data-active={t === tone}
                  aria-pressed={t === tone}
                  onClick={() => setTone(t)}
                >
                  {t}
                </button>
              ))}
            </div>
          </div>

          <div className="choice-group">
            <span className="field__label">Length</span>
            <div className="choice-row">
              {LENGTHS.map((l) => (
                <button
                  key={l}
                  type="button"
                  className="choice__btn"
                  data-active={l === length}
                  aria-pressed={l === length}
                  onClick={() => setLength(l)}
                >
                  {l}
                </button>
              ))}
            </div>
          </div>

          {letterError && (
            <Alert severity="error" sx={{ mb: 3 }}>
              {letterError}
            </Alert>
          )}

          {letterBlocked && coverLetter && (
            <Alert severity="warning" sx={{ mb: 3 }}>
              <AlertTitle>Couldn&apos;t verify</AlertTitle>
              <ul className="notice__list">
                {coverLetter.unverifiable.map((u, i) => (
                  <li key={i}>{u}</li>
                ))}
              </ul>
            </Alert>
          )}

          {!letterBlocked && coverLetter && (
            <Box className="downloads" sx={{ display: "flex", gap: 2, flexWrap: "wrap" }}>
              {coverLetter.pdfUrl && (
                <Button variant="outlined" component="a" href={coverLetter.pdfUrl} download>
                  Cover letter (PDF)
                </Button>
              )}
              {coverLetter.docxUrl && (
                <Button variant="outlined" component="a" href={coverLetter.docxUrl} download>
                  Cover letter (DOCX)
                </Button>
              )}
            </Box>
          )}

          {!letterBlocked && coverLetter && (
            <DocumentEditor
              kind="cover-letter"
              initial={coverLetter.text ?? ""}
            />
          )}

          <Box className="stage__actions" sx={{ display: "flex", gap: 2 }}>
            <Button variant="contained" disabled={letterBusy} onClick={makeLetter}>
              {letterBusy
                ? "Writing…"
                : coverLetter
                  ? "Regenerate letter"
                  : "Generate cover letter"}
            </Button>
          </Box>
        </section>
      )}

      <Box className="stage__actions" sx={{ display: "flex", gap: 2 }}>
        <Button variant="outlined" onClick={() => onBack("confirm")}>
          {blocked ? "Review inferences" : "Back"}
        </Button>
      </Box>
    </section>
  );
}
