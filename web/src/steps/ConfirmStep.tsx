import Box from "@mui/material/Box";
import Button from "@mui/material/Button";
import Alert from "@mui/material/Alert";
import Typography from "@mui/material/Typography";
import type { StepProps } from "../wizard/steps";
import { useWizard } from "../wizard/store";
import { confirmInferences } from "../api/client";
import "../styles/step.css";

export function ConfirmStep({ onAdvance, onBack }: StepProps) {
  const { inferences, approvals, edits, setApproval, setEdit, run, loading, error } =
    useWizard();

  // The claim the user is vouching for: their edit if present, else the original.
  const claimOf = (id: string, original: string) => edits[id] ?? original;

  const submit = async () => {
    const approved = inferences
      .filter((i) => approvals[i.id])
      .map((i) => ({
        id: i.id,
        claim: claimOf(i.id, i.claim).trim(),
        experienceId: i.experienceId,
      }))
      .filter((a) => a.claim.length > 0);
    const ok = await run(async () => {
      await confirmInferences(approved);
      return true;
    });
    if (ok) onAdvance("download");
  };

  return (
    <section>
      <div className="stage__head">
        <Typography variant="overline" className="eyebrow">Step 4 of 5</Typography>
        <h1 className="stage__title">Confirm anything we inferred</h1>
        <p className="stage__lede">
          Tailoring suggested a few claims that aren&apos;t in your truth file yet.
          Approve the ones that are true — reword them to match your own experience
          — and the rest never reach your CV.
        </p>
      </div>

      {error && (
        <Alert severity="error" sx={{ mb: 3 }}>
          {error}
        </Alert>
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

      <Box className="stage__actions" sx={{ display: "flex", gap: 2 }}>
        <Button variant="outlined" onClick={() => onBack("posting")}>
          Back
        </Button>
        <Button variant="contained" disabled={loading} onClick={submit}>
          {loading ? "Saving…" : "Confirm & continue"}
        </Button>
      </Box>
    </section>
  );
}
