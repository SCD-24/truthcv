import { useEffect, useState } from "react";
import type { StepProps } from "../wizard/steps";
import { useWizard } from "../wizard/store";
import { getTruth, saveTruth } from "../api/client";
import type { TruthEntry } from "../api/types";
import "../styles/step.css";

// At review time every entry is trustworthy — either attested from the PDF or a
// previously user-confirmed fact — so both read as green (attested). The rust
// variant is reserved for the Confirm step, where unverified inferences live.
function Stamp({ source }: { source: TruthEntry["source"] }) {
  return (
    <span className="stamp stamp--attested">
      {source === "linkedin-pdf" ? "Attested · linkedin" : "Confirmed · you"}
    </span>
  );
}

export function ReviewStep({ onAdvance, onBack }: StepProps) {
  const { truth, setTruth, run, loading, error } = useWizard();
  const [entries, setEntries] = useState<TruthEntry[]>(truth);

  // Load the truth file on first visit if the store has none yet.
  useEffect(() => {
    if (truth.length === 0) {
      run(async () => {
        const { entries: loaded } = await getTruth();
        setTruth(loaded);
        setEntries(loaded);
        return true;
      });
    } else {
      setEntries(truth);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const edit = (id: string, value: string) =>
    setEntries((prev) => prev.map((e) => (e.id === id ? { ...e, value } : e)));

  const remove = (id: string) =>
    setEntries((prev) => prev.filter((e) => e.id !== id));

  const save = async () => {
    const ok = await run(async () => {
      const cleaned = entries.filter((e) => e.value.trim() !== "");
      await saveTruth(cleaned);
      setTruth(cleaned);
      return true;
    });
    if (ok) onAdvance("posting");
  };

  return (
    <section>
      <div className="stage__head">
        <p className="eyebrow">Step 2 of 5</p>
        <h1 className="stage__title">Review what we found</h1>
        <p className="stage__lede">
          Every entry is stamped with where it came from. Correct anything that is
          wrong — once you save, these become the facts we stand behind.
        </p>
      </div>

      {error && (
        <p className="notice notice--error" role="alert">
          {error}
        </p>
      )}
      {loading && entries.length === 0 && (
        <p className="busy">Reading your truth file…</p>
      )}

      <div className="ledger">
        {entries.map((e) => (
          <article className="entry" key={e.id}>
            <div className="entry__top">
              <span className="entry__kind">{e.kind}</span>
              <span className="entry__meta">
                <Stamp source={e.source} />
                <button
                  type="button"
                  className="entry__remove"
                  onClick={() => remove(e.id)}
                >
                  Remove
                </button>
              </span>
            </div>
            <input
              className="entry__value"
              value={e.value}
              aria-label={`${e.kind} value`}
              onChange={(ev) => edit(e.id, ev.target.value)}
            />
          </article>
        ))}
      </div>

      <div className="stage__actions">
        <button type="button" className="btn btn--ghost" onClick={() => onBack("upload")}>
          Back
        </button>
        <button
          type="button"
          className="btn btn--primary"
          disabled={loading || entries.length === 0}
          onClick={save}
        >
          Save &amp; continue
        </button>
      </div>
    </section>
  );
}
