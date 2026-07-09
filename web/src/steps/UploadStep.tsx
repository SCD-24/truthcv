import { useRef, useState } from "react";
import type { StepProps } from "../wizard/steps";
import { useWizard } from "../wizard/store";
import { extractTruth, uploadPdf } from "../api/client";
import "../styles/step.css";

export function UploadStep({ onAdvance }: StepProps) {
  const { run, setTruth, hasProfile, loading, error } = useWizard();
  const [file, setFile] = useState<File | null>(null);
  const [dragging, setDragging] = useState(false);
  const [localError, setLocalError] = useState<string | null>(null);
  const inputRef = useRef<HTMLInputElement>(null);

  // Re-extract from the profile already saved on the server, skipping upload.
  const useSaved = async () => {
    const ok = await run(async () => {
      const { entries } = await extractTruth();
      setTruth(entries);
      return true;
    });
    if (ok) onAdvance("review");
  };

  const choose = (picked: File | undefined) => {
    if (!picked) return;
    if (picked.type !== "application/pdf" && !picked.name.endsWith(".pdf")) {
      setLocalError("That isn't a PDF. Export your LinkedIn profile as PDF and try again.");
      return;
    }
    setLocalError(null);
    setFile(picked);
  };

  const submit = async () => {
    if (!file) return;
    const ok = await run(async () => {
      await uploadPdf(file);
      const { entries } = await extractTruth();
      setTruth(entries);
      return true;
    });
    if (ok) onAdvance("review");
  };

  return (
    <section>
      <div className="stage__head">
        <p className="eyebrow">Step 1 of 5</p>
        <h1 className="stage__title">Start from what you can prove</h1>
        <p className="stage__lede">
          Upload your LinkedIn profile as a PDF. We read it into a truth file —
          the single record of facts your CV is allowed to draw from.
        </p>
      </div>

      {(localError || error) && (
        <p className="notice notice--error" role="alert">
          {localError || error}
        </p>
      )}

      {hasProfile && (
        <div className="saved-profile" role="status">
          <div>
            <strong>Saved profile found</strong>
            <p className="saved-profile__hint">
              Pick up from the profile you uploaded earlier, or upload a new PDF
              below.
            </p>
          </div>
          <button
            type="button"
            className="btn btn--primary"
            disabled={loading}
            onClick={useSaved}
          >
            Use saved profile
          </button>
        </div>
      )}

      <div
        className="dropzone"
        data-drag={dragging}
        role="button"
        tabIndex={0}
        aria-label="Upload a PDF"
        onClick={() => inputRef.current?.click()}
        onKeyDown={(e) => {
          if (e.key === "Enter" || e.key === " ") {
            e.preventDefault();
            inputRef.current?.click();
          }
        }}
        onDragOver={(e) => {
          e.preventDefault();
          setDragging(true);
        }}
        onDragLeave={() => setDragging(false)}
        onDrop={(e) => {
          e.preventDefault();
          setDragging(false);
          choose(e.dataTransfer.files[0]);
        }}
      >
        <strong>Drop your LinkedIn PDF here</strong>
        <p className="dropzone__hint">or click to choose a file</p>
        {file && <p className="dropzone__file">{file.name}</p>}
        <input
          ref={inputRef}
          type="file"
          accept="application/pdf,.pdf"
          className="sr-only"
          onChange={(e) => choose(e.target.files?.[0])}
        />
      </div>

      <div className="stage__actions">
        {loading && <span className="busy">Reading your profile…</span>}
        <button
          type="button"
          className="btn btn--primary"
          disabled={!file || loading}
          onClick={submit}
        >
          Continue to review
        </button>
      </div>
    </section>
  );
}
