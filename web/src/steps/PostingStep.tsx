import { useState } from "react";
import type { StepProps } from "../wizard/steps";
import { useWizard } from "../wizard/store";
import { fetchPosting, tailor } from "../api/client";
import "../styles/step.css";

export function PostingStep({ onAdvance, onBack }: StepProps) {
  const { posting, setPosting, setTailor, run, loading, error } = useWizard();
  const [url, setUrl] = useState("");
  const [fetching, setFetching] = useState(false);

  const fetchFromUrl = async () => {
    if (!url.trim()) return;
    setFetching(true);
    // Best-effort: on failure the user just pastes manually, so swallow errors.
    try {
      const { text } = await fetchPosting(url.trim());
      if (text) setPosting(text);
    } catch {
      /* fall back to manual paste */
    } finally {
      setFetching(false);
    }
  };

  const submit = async () => {
    if (!posting.trim()) return;
    const result = await run(() => tailor(posting.trim()));
    if (result) {
      setTailor(result);
      onAdvance("confirm");
    }
  };

  return (
    <section>
      <div className="stage__head">
        <p className="eyebrow">Step 3 of 5</p>
        <h1 className="stage__title">Paste the job you&apos;re after</h1>
        <p className="stage__lede">
          Drop in the posting — or fetch it from a URL. We tailor your CV to it
          using only the facts in your truth file.
        </p>
      </div>

      {error && (
        <p className="notice notice--error" role="alert">
          {error}
        </p>
      )}

      <div className="field">
        <label className="field__label" htmlFor="posting-url">
          Fetch from a URL (optional)
        </label>
        <div className="row">

          <input
            id="posting-url"
            className="input"
            type="url"
            placeholder="https://…"
            value={url}
            onChange={(e) => setUrl(e.target.value)}
          />
          <button
            type="button"
            className="btn btn--ghost"
            disabled={!url.trim() || fetching}
            onClick={fetchFromUrl}
          >
            {fetching ? "Fetching…" : "Fetch"}
          </button>
        </div>
      </div>

      <div className="field">
        <label className="field__label" htmlFor="posting-text">
          Job posting
        </label>
        <textarea
          id="posting-text"
          className="textarea"
          placeholder="Paste the full job description here…"
          value={posting}
          onChange={(e) => setPosting(e.target.value)}
        />
      </div>

      <div className="stage__actions">
        <button type="button" className="btn btn--ghost" onClick={() => onBack("review")}>
          Back
        </button>
        <button
          type="button"
          className="btn btn--primary"
          disabled={!posting.trim() || loading}
          onClick={submit}
        >
          {loading ? "Tailoring…" : "Tailor my CV"}
        </button>
      </div>
    </section>
  );
}
