import type { StepProps } from "../wizard/steps";
import { useWizard } from "../wizard/store";
import { confirmInferences } from "../api/client";
import "../styles/step.css";

export function ConfirmStep({ onAdvance, onBack }: StepProps) {
  const { inferences, approvals, setApproval, run, loading, error } = useWizard();

  const submit = async () => {
    const approvedIds = inferences
      .filter((i) => approvals[i.id])
      .map((i) => i.id);
    const ok = await run(async () => {
      await confirmInferences(approvedIds);
      return true;
    });
    if (ok) onAdvance("download");
  };

  return (
    <section>
      <div className="stage__head">
        <p className="eyebrow">Step 4 of 5</p>
        <h1 className="stage__title">Confirm anything we inferred</h1>
        <p className="stage__lede">
          Tailoring suggested a few claims that aren&apos;t in your truth file yet.
          Approve the ones that are true; the rest never reach your CV.
        </p>
      </div>

      {error && (
        <p className="notice notice--error" role="alert">
          {error}
        </p>
      )}

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
                <p className="inference__claim">{inf.claim}</p>
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

      <div className="stage__actions">
        <button type="button" className="btn btn--ghost" onClick={() => onBack("posting")}>
          Back
        </button>
        <button
          type="button"
          className="btn btn--primary"
          disabled={loading}
          onClick={submit}
        >
          {loading ? "Saving…" : "Confirm & continue"}
        </button>
      </div>
    </section>
  );
}
