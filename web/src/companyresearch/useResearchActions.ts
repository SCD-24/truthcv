import { useState } from "react";
import { createCompanyFinding, resolveCompanyFinding } from "../api/client";
import type { CompanyFinding } from "../api/types";
import type { FindingDraft } from "./FindingDialog";
import type { CardActions } from "./ResearchList";
import { errorMessage } from "./useResearchPage";
import type { ResearchView } from "./useResearchPage";

/** Which finding the dialog is open for: none (closed), a new one, or a
 * correction of an existing one. */
type DialogState = null | { finding?: CompanyFinding };

/** Accept or reject a finding, then refetch so the contradiction clears. The
 * cards stay busy until that refetch has settled, so a stale contradiction is
 * never actionable twice. A refetch failure surfaces as a load error. */
function useResolve(view: ResearchView, setActionError: (e: string | null) => void) {
  const [busy, setBusy] = useState(false);
  async function onResolve(id: string, resolution: "accepted" | "rejected") {
    setBusy(true);
    setActionError(null);
    try {
      await resolveCompanyFinding(id, resolution);
      await view.refetch();
    } catch (e) {
      setActionError(errorMessage(e, "Couldn't record your decision."));
    } finally {
      setBusy(false);
    }
  }
  return { busy, onResolve };
}

/** The card actions, the action error, and the add/correct dialog's state. */
export function useResearchActions(view: ResearchView) {
  const [actionError, setActionError] = useState<string | null>(null);
  const [dialog, setDialog] = useState<DialogState>(null);
  const resolve = useResolve(view, setActionError);

  /** Record a finding (new or superseding) and refetch. A create error
   * propagates to the dialog; a refetch error is a load error. */
  async function handleSubmit(draft: FindingDraft) {
    await createCompanyFinding(draft);
    void view.refetch();
  }

  const actions: CardActions = { ...resolve, onCorrect: (finding) => setDialog({ finding }) };
  return { actions, actionError, setActionError, dialog, setDialog, handleSubmit };
}
