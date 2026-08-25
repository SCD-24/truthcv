import { useRef, useState } from "react";
import Box from "@mui/material/Box";
import Button from "@mui/material/Button";
import Alert from "@mui/material/Alert";
import Typography from "@mui/material/Typography";
import { useWizard } from "../wizard/store";
import { extractTruth, uploadCv } from "../api/client";
import { ButtonSpinner } from "../components/ButtonSpinner";
import "../styles/step.css";

export interface UploadStepProps {
  onNext: () => void;
  onBack?: () => void;
}

export function UploadStep({ onNext }: UploadStepProps) {
  const { run, setTruth, loading, error } = useWizard();
  const [file, setFile] = useState<File | null>(null);
  const [dragging, setDragging] = useState(false);
  const [localError, setLocalError] = useState<string | null>(null);
  const inputRef = useRef<HTMLInputElement>(null);

  const SUPPORTED_EXTENSIONS = [".pdf", ".docx", ".txt", ".md"];

  const choose = (picked: File | undefined) => {
    if (!picked) return;
    const name = picked.name.toLowerCase();
    if (!SUPPORTED_EXTENSIONS.some((ext) => name.endsWith(ext))) {
      setLocalError("Unsupported file type. Upload your CV as PDF, DOCX, TXT, or MD.");
      return;
    }
    setLocalError(null);
    setFile(picked);
  };

  const submit = async () => {
    if (!file) return;
    const ok = await run(async () => {
      await uploadCv(file);
      setTruth(await extractTruth());
      return true;
    });
    if (ok) onNext();
  };

  return (
    <section>
      <div className="stage__head">
        <Typography variant="overline" className="eyebrow">Step 1 of 2</Typography>
        <h1 className="hero__title">Every line, traceable.</h1>
        <p className="stage__lede">
          Upload your CV — PDF, Word, text or Markdown. We read it into your
          truth file — the one record your CV can draw from. Every claim keeps
          a link back to where it came from.
        </p>
      </div>

      {/* Signature: the source-trace. A worked example of the mechanism — one
          source, every claim branching from it, each stamped with its
          provenance. Decorative; the real controls are below. */}
      <figure className="trace" aria-hidden="true">
        <ul className="trace__list">
          <li className="trace__root">
            <span className="trace__doc">▤</span>
            <span className="trace__source">CV.pdf</span>
          </li>
          <li className="claim claim--attested">
            <span className="claim__text">Senior Engineer · Acme</span>
            <span className="stamp stamp--attested">Attested · CV</span>
          </li>
          <li className="claim claim--attested">
            <span className="claim__text">Led the Kubernetes migration</span>
            <span className="stamp stamp--attested">Attested · CV</span>
          </li>
          <li className="claim claim--inferred">
            <span className="claim__text">“Grew the team 3×”</span>
            <span className="stamp stamp--inferred">Inferred · needs you</span>
          </li>
        </ul>
        <figcaption className="trace__caption">
          Green is proven. Rust is a claim we can’t trace yet — you decide.
        </figcaption>
      </figure>

      {(localError || error) && (
        <Alert severity="error" sx={{ mb: 3 }}>
          {localError || error}
        </Alert>
      )}

      <div
        className="dropzone"
        data-drag={dragging}
        role="button"
        tabIndex={0}
        aria-label="Upload your CV"
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
        <strong>Drop your CV here</strong>
        <p className="dropzone__hint">or click to choose a file</p>
        {file && <p className="dropzone__file">{file.name}</p>}
        <input
          ref={inputRef}
          type="file"
          accept=".pdf,.docx,.txt,.md,application/pdf,application/vnd.openxmlformats-officedocument.wordprocessingml.document,text/plain,text/markdown"
          className="sr-only"
          onChange={(e) => choose(e.target.files?.[0])}
        />
      </div>

      <Box className="stage__actions" sx={{ display: "flex", alignItems: "center", gap: 2 }}>
        {loading && (
          <Typography variant="body2" sx={{ color: "text.secondary" }}>
            Reading your profile…
          </Typography>
        )}
        <Button variant="contained" disabled={!file || loading} onClick={submit}>
          {loading && <ButtonSpinner />}
          Continue to review
        </Button>
      </Box>
    </section>
  );
}
