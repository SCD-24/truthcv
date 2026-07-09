import { STEPS, stepIndex, type StepId } from "./steps";

interface Props {
  current: StepId;
  reached: StepId;
  onNavigate: (to: StepId) => void;
}

/** The step rail — the wizard presented as an auditable record of progress. */
export function StepRail({ current, reached, onNavigate }: Props) {
  const reachedIdx = stepIndex(reached);
  const currentIdx = stepIndex(current);

  return (
    <nav className="rail" aria-label="Wizard steps">
      <div className="rail__brand">
        Truth<span>CV</span>
      </div>

      <ol className="rail__steps">
        {STEPS.map((step, i) => {
          const state =
            i === currentIdx ? "current" : i < reachedIdx ? "done" : "upcoming";
          const reachable = i <= reachedIdx;
          return (
            <li key={step.id}>
              <button
                type="button"
                className="rail__step"
                data-state={state}
                disabled={!reachable}
                aria-current={state === "current" ? "step" : undefined}
                onClick={() => reachable && onNavigate(step.id)}
              >
                <span className="rail__marker" aria-hidden="true">
                  {state === "done" ? "✓" : i + 1}
                </span>
                <span className="rail__label">{step.label}</span>
              </button>
            </li>
          );
        })}
      </ol>

      <p className="rail__foot">
        Every fact traces back to a source. Nothing reaches your CV unless it does.
      </p>
    </nav>
  );
}
