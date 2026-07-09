import { useEffect, useState } from "react";
import type { StepProps } from "../wizard/steps";
import { useWizard } from "../wizard/store";
import { generateCoverLetter, render as renderCv } from "../api/client";
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
        <p className="eyebrow">Step 5 of 5</p>
        <h1 className="stage__title">
          {blocked ? "One more check before you download" : "A CV you can stand behind"}
        </h1>
        <p className="stage__lede">
          {blocked
            ? "The guardrail found claims it couldn't trace back to your truth file. Nothing ships until every fact checks out."
            : "We checked every fact against your truth file and ran an ATS review. Download it as PDF or DOCX."}
        </p>
      </div>

      {loading && <p className="busy">Checking every fact against your truth file…</p>}
      {error && (
        <p className="notice notice--error" role="alert">
          {error}
        </p>
      )}

      {blocked && result && (
        <div className="notice notice--warn" role="alert">
          <strong>Couldn&apos;t verify:</strong>
          <ul className="notice__list">
            {result.unverifiable.map((u, i) => (
              <li key={i}>{u}</li>
            ))}
          </ul>
        </div>
      )}

      {!blocked && result && result.atsWarnings.length > 0 && (
        <div className="notice notice--warn">
          <strong>ATS review:</strong>
          <ul className="notice__list">
            {result.atsWarnings.map((w) => (
              <li key={w.code}>{w.message}</li>
            ))}
          </ul>
        </div>
      )}

      {!blocked && result && (
        <div className="downloads">
          {result.pdfUrl && (
            <a className="download" href={result.pdfUrl} download>
              Download PDF
            </a>
          )}
          {result.docxUrl && (
            <a className="download" href={result.docxUrl} download>
              Download DOCX
            </a>
          )}
        </div>
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
            <p className="notice notice--error" role="alert">
              {letterError}
            </p>
          )}

          {letterBlocked && coverLetter && (
            <div className="notice notice--warn" role="alert">
              <strong>Couldn&apos;t verify:</strong>
              <ul className="notice__list">
                {coverLetter.unverifiable.map((u, i) => (
                  <li key={i}>{u}</li>
                ))}
              </ul>
            </div>
          )}

          {!letterBlocked && coverLetter && (
            <div className="downloads">
              {coverLetter.pdfUrl && (
                <a className="download" href={coverLetter.pdfUrl} download>
                  Cover letter (PDF)
                </a>
              )}
              {coverLetter.docxUrl && (
                <a className="download" href={coverLetter.docxUrl} download>
                  Cover letter (DOCX)
                </a>
              )}
            </div>
          )}

          <div className="stage__actions">
            <button
              type="button"
              className="btn btn--primary"
              disabled={letterBusy}
              onClick={makeLetter}
            >
              {letterBusy
                ? "Writing…"
                : coverLetter
                  ? "Regenerate letter"
                  : "Generate cover letter"}
            </button>
          </div>
        </section>
      )}

      <div className="stage__actions">
        <button type="button" className="btn btn--ghost" onClick={() => onBack("confirm")}>
          {blocked ? "Review inferences" : "Back"}
        </button>
      </div>
    </section>
  );
}
