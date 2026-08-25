import { useCallback, useEffect, useRef, useState } from "react";
import Box from "@mui/material/Box";
import Button from "@mui/material/Button";
import Alert from "@mui/material/Alert";
import AlertTitle from "@mui/material/AlertTitle";
import Typography from "@mui/material/Typography";
import TextField from "@mui/material/TextField";
import Checkbox from "@mui/material/Checkbox";
import FormGroup from "@mui/material/FormGroup";
import FormControl from "@mui/material/FormControl";
import FormLabel from "@mui/material/FormLabel";
import FormControlLabel from "@mui/material/FormControlLabel";
import RadioGroup from "@mui/material/RadioGroup";
import Radio from "@mui/material/Radio";
import {
  confirmInferences,
  createApplication,
  generateCoverLetter,
  render as renderCv,
  tailor,
} from "../api/client";
import type {
  CoverLetterResult,
  Inference,
  RenderResult,
  TailorResult,
} from "../api/types";
import { ButtonSpinner } from "../components/ButtonSpinner";
import {
  approvalsFrom,
  BlockedClaimsPanel,
  type Decision,
} from "../components/BlockedClaimsPanel";
import { DocumentEditor } from "../steps/DocumentEditor";
import "../styles/step.css";

const TONES = ["Professional", "Warm", "Concise"] as const;
const LENGTHS = ["Short", "Standard"] as const;
type Tone = (typeof TONES)[number];
type Length = (typeof LENGTHS)[number];

/** Human-readable message from a thrown value, with a fallback. */
function errText(e: unknown, fallback: string): string {
  return e instanceof Error ? e.message : fallback;
}

/**
 * ManualPage — a single page that (optionally) creates an application record
 * for a posting and then generates a tailored CV and/or a cover letter. It
 * replaces the old three-step wizard (Posting → Confirm → Download): the form
 * captures the posting plus the company details, the CV path runs the
 * inference-confirmation guardrail before rendering, and the cover-letter path
 * generates directly. When both are requested the CV is finished first. Every
 * generated document is edited/attached through a DocumentEditor locked to the
 * record this session created, so a document can never land on the wrong
 * application. The id passed downstream is only ever the one returned by this
 * session's createApplication call (or undefined).
 */
export function ManualPage() {
  // Form state (PART A).
  const [posting, setPosting] = useState("");
  const [company, setCompany] = useState("");
  const [role, setRole] = useState("");
  const [website, setWebsite] = useState("");
  const [applicationUrl, setApplicationUrl] = useState("");
  const [wantCv, setWantCv] = useState(true);
  const [wantLetter, setWantLetter] = useState(false);
  const [createRecord, setCreateRecord] = useState<"yes" | "no">("no");

  // Generation state (PART B).
  const [submitted, setSubmitted] = useState(false);
  const [applicationId, setApplicationId] = useState<string | undefined>(undefined);
  const [recordWarning, setRecordWarning] = useState<string | null>(null);
  const [cvDone, setCvDone] = useState(false);

  const canSubmit =
    posting.trim().length > 0 &&
    company.trim().length > 0 &&
    role.trim().length > 0 &&
    website.trim().length > 0 &&
    applicationUrl.trim().length > 0 &&
    (wantCv || wantLetter);

  // On submit: create the record first (if the user opted in), then reveal the
  // generation half. A record failure is non-blocking — documents just stay
  // unattached. When the user opted out, createApplication is never called and
  // applicationId stays undefined, so no stale id ever reaches downstream calls.
  const submit = useCallback(async () => {
    if (createRecord === "yes") {
      try {
        const app = await createApplication({
          company: company.trim(),
          website: website.trim(),
          applicationUrl: applicationUrl.trim(),
          posting: posting.trim(),
        });
        setApplicationId(app.id);
      } catch {
        setRecordWarning(
          "we could not create the record; your documents will not be attached",
        );
      }
    }
    setSubmitted(true);
  }, [createRecord, company, website, applicationUrl, posting]);

  // The letter path only starts once the CV path has fully rendered (when a CV
  // was also requested); on its own it starts immediately.
  const showLetter = submitted && wantLetter && (!wantCv || cvDone);

  return (
    <section>
      <div className="stage__head">
        <Typography variant="overline" className="eyebrow">
          Manual
        </Typography>
        <h1 className="stage__title">Tailor a CV or cover letter</h1>
        <p className="stage__lede">
          Paste the posting, tell us who it&apos;s for, and pick what to
          generate. We tailor to it using only the facts in your truth file.
        </p>
      </div>

      <Box data-tour="manual-posting" sx={{ mb: 3 }}>
        <TextField
          id="posting-text"
          label="Job posting"
          placeholder="Paste the full job description here…"
          value={posting}
          onChange={(e) => setPosting(e.target.value)}
          multiline
          minRows={10}
          fullWidth
        />
      </Box>

      <Box sx={{ display: "grid", gap: 2, mb: 3 }}>
        <TextField
          label="Company"
          value={company}
          onChange={(e) => setCompany(e.target.value)}
          required
          fullWidth
        />
        <TextField
          label="Role"
          value={role}
          onChange={(e) => setRole(e.target.value)}
          required
          fullWidth
        />
        <TextField
          label="Website"
          value={website}
          onChange={(e) => setWebsite(e.target.value)}
          required
          fullWidth
        />
        <TextField
          label="Application URL"
          value={applicationUrl}
          onChange={(e) => setApplicationUrl(e.target.value)}
          required
          fullWidth
        />
      </Box>

      <FormControl component="fieldset" sx={{ mb: 2 }} data-tour="manual-outputs">
        <FormLabel component="legend">What should we generate?</FormLabel>
        <FormGroup>
          <FormControlLabel
            control={
              <Checkbox
                checked={wantCv}
                onChange={(e) => setWantCv(e.target.checked)}
              />
            }
            label="Tailor my CV"
          />
          <FormControlLabel
            control={
              <Checkbox
                checked={wantLetter}
                onChange={(e) => setWantLetter(e.target.checked)}
              />
            }
            label="Write a cover letter"
          />
        </FormGroup>
      </FormControl>

      <FormControl
        component="fieldset"
        sx={{ mb: 3, display: "block" }}
        data-tour="manual-record"
      >
        <FormLabel component="legend">
          Create an application record for this posting?
        </FormLabel>
        <RadioGroup
          row
          value={createRecord}
          onChange={(e) => setCreateRecord(e.target.value as "yes" | "no")}
        >
          <FormControlLabel value="yes" control={<Radio />} label="Yes" />
          <FormControlLabel value="no" control={<Radio />} label="No" />
        </RadioGroup>
      </FormControl>

      <Box className="stage__actions" sx={{ display: "flex", gap: 2, mb: 3 }}>
        <Button
          variant="contained"
          disabled={!canSubmit || submitted}
          onClick={submit}
        >
          Generate
        </Button>
      </Box>

      {recordWarning && (
        <Alert severity="warning" sx={{ mb: 3 }}>
          {recordWarning}
        </Alert>
      )}

      {submitted && wantCv && (
        <CvSection
          posting={posting.trim()}
          applicationId={applicationId}
          onRendered={() => setCvDone(true)}
        />
      )}

      {showLetter && <LetterSection applicationId={applicationId} />}
    </section>
  );
}

/** The inference ledger (ported from ConfirmStep) plus the confirm button. The
 * claim vouched for is the user's edit if present, else the original. */
function InferenceLedger({
  inferences,
  approvals,
  edits,
  setApproval,
  setEdit,
  onConfirm,
  busy,
}: {
  inferences: Inference[];
  approvals: Record<string, boolean>;
  edits: Record<string, string>;
  setApproval: (id: string, approved: boolean) => void;
  setEdit: (id: string, claim: string) => void;
  onConfirm: () => void;
  busy: boolean;
}) {
  const claimOf = (id: string, original: string) => edits[id] ?? original;
  return (
    <>
      {inferences.length === 0 ? (
        <p className="busy">
          Nothing to confirm — every tailored claim already traces to your truth
          file. You&apos;re clear to continue.
        </p>
      ) : (
        <div className="ledger">
          {inferences.map((inf) => {
            const decided = inf.id in approvals;
            const approved = approvals[inf.id] === true;
            return (
              <article
                className="inference"
                key={inf.id}
                data-approved={decided ? String(approved) : undefined}
              >
                {approved ? (
                  <label className="inference__edit">
                    <span className="inference__editLabel">
                      Your words — this is what goes on the CV
                    </span>
                    <textarea
                      className="input inference__claimInput"
                      value={claimOf(inf.id, inf.claim)}
                      onChange={(e) => setEdit(inf.id, e.target.value)}
                      rows={2}
                      aria-label={`Edit claim: ${inf.claim}`}
                    />
                  </label>
                ) : (
                  <p className="inference__claim">{claimOf(inf.id, inf.claim)}</p>
                )}
                <p className="inference__rationale">{inf.rationale}</p>
                <div
                  className="choice"
                  role="group"
                  aria-label={`Decision for: ${inf.claim}`}
                >
                  <button
                    type="button"
                    className="choice__btn"
                    data-active={approved ? "approve" : undefined}
                    aria-pressed={approved}
                    onClick={() => setApproval(inf.id, true)}
                  >
                    True — include it
                  </button>
                  <button
                    type="button"
                    className="choice__btn"
                    data-active={decided && !approved ? "reject" : undefined}
                    aria-pressed={decided && !approved}
                    onClick={() => setApproval(inf.id, false)}
                  >
                    Leave it out
                  </button>
                </div>
              </article>
            );
          })}
        </div>
      )}
      <Box className="stage__actions" sx={{ display: "flex", gap: 2, mt: 2 }}>
        <Button variant="contained" disabled={busy} onClick={onConfirm}>
          {busy && <ButtonSpinner />}
          {busy ? "Saving…" : "Confirm & continue"}
        </Button>
      </Box>
    </>
  );
}

/** Download buttons (ported from DownloadStep) for a rendered document. */
function DownloadLinks({
  pdfUrl,
  docxUrl,
  label,
}: {
  pdfUrl: string | null;
  docxUrl: string | null;
  label: string;
}) {
  return (
    <Box className="downloads" sx={{ display: "flex", gap: 2, flexWrap: "wrap", mb: 2 }}>
      {pdfUrl && (
        <Button variant="outlined" component="a" href={pdfUrl} download>
          {label} (PDF)
        </Button>
      )}
      {docxUrl && (
        <Button variant="outlined" component="a" href={docxUrl} download>
          {label} (DOCX)
        </Button>
      )}
    </Box>
  );
}

/** A labelled row of toggle buttons (ported from DownloadStep's tone/length). */
function ChoiceGroup<T extends string>({
  label,
  options,
  value,
  onChange,
}: {
  label: string;
  options: readonly T[];
  value: T;
  onChange: (v: T) => void;
}) {
  return (
    <div className="choice-group">
      <span className="field__label">{label}</span>
      <div className="choice-row">
        {options.map((o) => (
          <button
            key={o}
            type="button"
            className="choice__btn"
            data-active={o === value}
            aria-pressed={o === value}
            onClick={() => onChange(o)}
          >
            {o}
          </button>
        ))}
      </div>
    </div>
  );
}

/**
 * The CV half: tailor → confirm inferences → render, with the blocked-claims
 * re-check flow and an application-locked editor for the rendered CV. Calls
 * `onRendered` once the CV renders unblocked, so the page can release the
 * cover-letter half.
 */
function CvSection({
  posting,
  applicationId,
  onRendered,
}: {
  posting: string;
  applicationId?: string;
  onRendered: () => void;
}) {
  const [tailorResult, setTailorResult] = useState<TailorResult | null>(null);
  const [approvals, setApprovals] = useState<Record<string, boolean>>({});
  const [edits, setEdits] = useState<Record<string, string>>({});
  const [result, setResult] = useState<RenderResult | null>(null);
  const [decisions, setDecisions] = useState<Record<string, Decision>>({});
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const tailored = useRef(false);

  // Tailor once on first arrival — the posting is fixed for this section.
  useEffect(() => {
    if (tailored.current) return;
    tailored.current = true;
    setBusy(true);
    tailor(posting)
      .then((r) => setTailorResult(r))
      .catch((e) => setError(errText(e, "Couldn't tailor your CV.")))
      .finally(() => setBusy(false));
  }, [posting]);

  // Apply a render result, releasing the cover-letter half once it's unblocked.
  const applyResult = (r: RenderResult) => {
    setResult(r);
    if (!r.blocked) onRendered();
  };

  const confirmAndRender = async () => {
    if (!tailorResult) return;
    const claimOf = (id: string, original: string) => edits[id] ?? original;
    const approved = tailorResult.inferences
      .filter((i) => approvals[i.id])
      .map((i) => ({
        id: i.id,
        claim: claimOf(i.id, i.claim).trim(),
        experienceId: i.experienceId,
      }))
      .filter((a) => a.claim.length > 0);
    setBusy(true);
    setError(null);
    try {
      await confirmInferences(approved);
      applyResult(await renderCv(undefined, applicationId));
    } catch (e) {
      setError(errText(e, "Couldn't render the CV."));
    } finally {
      setBusy(false);
    }
  };

  const recheck = async () => {
    setBusy(true);
    setError(null);
    try {
      const payload = approvalsFrom(result?.blockedClaims ?? [], decisions);
      applyResult(await renderCv(payload, applicationId));
    } catch (e) {
      setError(errText(e, "Couldn't render the CV."));
    } finally {
      setBusy(false);
    }
  };

  return (
    <section className="cv-path" aria-labelledby="cv-path-title">
      <h2 id="cv-path-title" className="stage__title">
        Tailored CV
      </h2>
      {error && (
        <Alert severity="error" sx={{ mb: 3 }}>
          {error}
        </Alert>
      )}
      {busy && !tailorResult && (
        <Typography variant="body2" className="busy" sx={{ color: "text.secondary" }}>
          Tailoring your CV to the posting…
        </Typography>
      )}

      {tailorResult && !result && (
        <InferenceLedger
          inferences={tailorResult.inferences}
          approvals={approvals}
          edits={edits}
          setApproval={(id, approved) =>
            setApprovals((prev) => ({ ...prev, [id]: approved }))
          }
          setEdit={(id, claim) => setEdits((prev) => ({ ...prev, [id]: claim }))}
          onConfirm={confirmAndRender}
          busy={busy}
        />
      )}

      {result?.blocked && (
        <BlockedClaimsPanel
          claims={result.blockedClaims}
          decisions={decisions}
          onDecide={(claimId, choice) =>
            setDecisions((prev) => ({ ...prev, [claimId]: choice }))
          }
          onRecheck={recheck}
          busy={busy}
          ariaLabel="Claims to approve or deny"
        />
      )}

      {result && !result.blocked && (
        <>
          {result.atsWarnings.length > 0 && (
            <Alert severity="warning" sx={{ mb: 3 }}>
              <AlertTitle>ATS review</AlertTitle>
              <ul className="notice__list">
                {result.atsWarnings.map((w, i) => (
                  <li key={`${w.code}-${i}`}>{w.message}</li>
                ))}
              </ul>
            </Alert>
          )}
          <DownloadLinks pdfUrl={result.pdfUrl} docxUrl={result.docxUrl} label="CV" />
          <DocumentEditor
            kind="cv"
            initial={result.html ?? ""}
            lockedAppId={applicationId ?? undefined}
          />
        </>
      )}
    </section>
  );
}

/**
 * The cover-letter half: generate directly (no tailor/confirm step) with the
 * tone/length pickers, the blocked-claims re-check flow, and an
 * application-locked editor for the generated letter.
 */
function LetterSection({ applicationId }: { applicationId?: string }) {
  const [tone, setTone] = useState<Tone>("Professional");
  const [length, setLength] = useState<Length>("Standard");
  const [coverLetter, setCoverLetter] = useState<CoverLetterResult | null>(null);
  const [decisions, setDecisions] = useState<Record<string, Decision>>({});
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const makeLetter = async (withApprovals: boolean) => {
    setBusy(true);
    setError(null);
    try {
      const approvals = withApprovals
        ? approvalsFrom(coverLetter?.blockedClaims ?? [], decisions)
        : undefined;
      const r = await generateCoverLetter(
        tone.toLowerCase(),
        length.toLowerCase(),
        approvals,
        applicationId,
      );
      setCoverLetter(r);
    } catch (e) {
      setError(errText(e, "Couldn't write the letter."));
    } finally {
      setBusy(false);
    }
  };

  return (
    <section className="letter-path" aria-labelledby="letter-path-title">
      <h2 id="letter-path-title" className="stage__title">
        Cover letter
      </h2>

      <ChoiceGroup label="Tone" options={TONES} value={tone} onChange={setTone} />
      <ChoiceGroup
        label="Length"
        options={LENGTHS}
        value={length}
        onChange={setLength}
      />

      {error && (
        <Alert severity="error" sx={{ mb: 3 }}>
          {error}
        </Alert>
      )}

      {coverLetter?.blocked && (
        <BlockedClaimsPanel
          claims={coverLetter.blockedClaims}
          decisions={decisions}
          onDecide={(claimId, choice) =>
            setDecisions((prev) => ({ ...prev, [claimId]: choice }))
          }
          onRecheck={() => makeLetter(true)}
          busy={busy}
          ariaLabel="Cover-letter claims to approve or deny"
        />
      )}

      {coverLetter && !coverLetter.blocked && (
        <>
          <DownloadLinks
            pdfUrl={coverLetter.pdfUrl}
            docxUrl={coverLetter.docxUrl}
            label="Cover letter"
          />
          <DocumentEditor
            kind="cover-letter"
            initial={coverLetter.text ?? ""}
            lockedAppId={applicationId ?? undefined}
          />
        </>
      )}

      <Box className="stage__actions" sx={{ display: "flex", gap: 2, mt: 2 }}>
        <Button
          variant="contained"
          disabled={busy}
          onClick={() => makeLetter(false)}
        >
          {busy && <ButtonSpinner />}
          {busy
            ? "Writing…"
            : coverLetter
              ? "Regenerate letter"
              : "Generate cover letter"}
        </Button>
      </Box>
    </section>
  );
}
