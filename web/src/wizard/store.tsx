import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useReducer,
  type ReactNode,
} from "react";
import type {
  CoverLetterResult,
  Inference,
  RenderResult,
  TailorResult,
  TruthDoc,
} from "../api/types";

const emptyProfile = {
  name: "",
  email: "",
  phone: "",
  location: "",
  links: [],
  summary: "",
};
const emptyTruth: TruthDoc = {
  experiences: [],
  education: [],
  skills: [],
  profile: emptyProfile,
};
import { extractTruth, getProfile } from "../api/client";

/**
 * Where the wizard should open once startup checks finish.
 * - "pending": still checking for a saved profile (show a splash, not the form)
 * - "upload": no saved profile — begin at step 1 as usual
 * - "posting": a saved profile was found and its truth loaded — skip to step 3,
 *   leaving Upload/Review reachable behind the user via back-navigation.
 */
export type Bootstrap = "pending" | "upload" | "posting";

/**
 * Shared wizard state. Holds the truth file, the posting, the inferences the
 * user is deciding on, and the render result — plus a single loading/error pair
 * that step components drive through the `run` helper so async UI is consistent.
 */
interface WizardState {
  truth: TruthDoc;
  posting: string;
  keywords: string[];
  inferences: Inference[];
  approvals: Record<string, boolean>;
  /** Per-inference edited claim text (id -> text). Absent keys use the
   * original claim; lets the user reword an inferred claim before confirming. */
  edits: Record<string, string>;
  /** Per-claim guardrail decisions at step 5, keyed by claimId. Render-scoped
   * only (never writes truth). Held here so they survive the step's remount on
   * back-navigation. */
  decisions: Record<string, "approve" | "deny">;
  render: RenderResult | null;
  coverLetter: CoverLetterResult | null;
  /** Whether a profile PDF is already saved server-side (skip re-upload). */
  hasProfile: boolean;
  /** Resolved startup destination; drives the wizard's opening step. */
  bootstrap: Bootstrap;
  loading: boolean;
  error: string | null;
}

const initialState: WizardState = {
  truth: emptyTruth,
  posting: "",
  keywords: [],
  inferences: [],
  approvals: {},
  edits: {},
  decisions: {},
  render: null,
  coverLetter: null,
  hasProfile: false,
  bootstrap: "pending",
  loading: false,
  error: null,
};

type Action =
  | { type: "loading" }
  | { type: "error"; error: string | null }
  | { type: "setTruth"; truth: TruthDoc }
  | { type: "setPosting"; posting: string }
  | { type: "setTailor"; result: TailorResult }
  | { type: "setApproval"; id: string; approved: boolean }
  | { type: "setEdit"; id: string; claim: string }
  | { type: "setDecision"; claimId: string; choice: "approve" | "deny" }
  | { type: "setRender"; result: RenderResult }
  | { type: "setCoverLetter"; result: CoverLetterResult }
  | { type: "setHasProfile"; hasProfile: boolean }
  | { type: "setBootstrap"; bootstrap: Bootstrap };

function reducer(state: WizardState, action: Action): WizardState {
  switch (action.type) {
    case "loading":
      return { ...state, loading: true, error: null };
    case "error":
      return { ...state, loading: false, error: action.error };
    case "setTruth":
      return { ...state, truth: action.truth, loading: false, error: null };
    case "setPosting":
      return { ...state, posting: action.posting };
    case "setTailor":
      return {
        ...state,
        keywords: action.result.keywords,
        inferences: action.result.inferences,
        // Undecided by default: keys appear only once the user chooses, so the
        // Confirm step can distinguish "not yet decided" from an explicit reject.
        approvals: {},
        // A fresh tailor run replaces the inferences, so any earlier edits no
        // longer refer to anything — clear them alongside approvals.
        edits: {},
        // A re-tailor invalidates prior guardrail decisions too.
        decisions: {},
        // A re-tailor invalidates any earlier render/letter drafts.
        render: null,
        coverLetter: null,
        loading: false,
        error: null,
      };
    case "setApproval":
      return {
        ...state,
        approvals: { ...state.approvals, [action.id]: action.approved },
      };
    case "setEdit":
      return {
        ...state,
        edits: { ...state.edits, [action.id]: action.claim },
      };
    case "setDecision":
      return {
        ...state,
        decisions: { ...state.decisions, [action.claimId]: action.choice },
      };
    case "setRender":
      return { ...state, render: action.result, loading: false, error: null };
    case "setCoverLetter":
      return { ...state, coverLetter: action.result };
    case "setHasProfile":
      return { ...state, hasProfile: action.hasProfile };
    case "setBootstrap":
      return { ...state, bootstrap: action.bootstrap };
    default:
      return state;
  }
}

interface WizardApi extends WizardState {
  setTruth: (truth: TruthDoc) => void;
  setPosting: (posting: string) => void;
  setTailor: (result: TailorResult) => void;
  setApproval: (id: string, approved: boolean) => void;
  setEdit: (id: string, claim: string) => void;
  setDecision: (claimId: string, choice: "approve" | "deny") => void;
  setRender: (result: RenderResult) => void;
  setCoverLetter: (result: CoverLetterResult) => void;
  /** Run an async task, driving loading/error and returning its result or null. */
  run: <T>(fn: () => Promise<T>) => Promise<T | null>;
}

const WizardContext = createContext<WizardApi | null>(null);

export function WizardProvider({ children }: { children: ReactNode }) {
  const [state, dispatch] = useReducer(reducer, initialState);

  const run = useCallback(async <T,>(fn: () => Promise<T>): Promise<T | null> => {
    dispatch({ type: "loading" });
    try {
      const result = await fn();
      dispatch({ type: "error", error: null });
      return result;
    } catch (err) {
      dispatch({
        type: "error",
        error: err instanceof Error ? err.message : "Something went wrong.",
      });
      return null;
    }
  }, []);

  // On load, decide the opening step from the cheap profile check ALONE, so the
  // splash can never hang: only /api/profile gates the splash. If a profile
  // exists we open straight at Posting (step 3) and load its truth in the
  // background — the extract is free when the source is unchanged, so returning
  // users skip re-upload without re-spending tokens, and a slow/failed extract
  // surfaces on the step (never as a stuck splash). Any profile-check failure
  // falls back to Upload so the user is never stranded.
  useEffect(() => {
    let alive = true;
    getProfile()
      .then((p) => {
        if (!alive) return;
        dispatch({ type: "setHasProfile", hasProfile: p.hasProfile });
        dispatch({
          type: "setBootstrap",
          bootstrap: p.hasProfile ? "posting" : "upload",
        });
        if (p.hasProfile) {
          // Background: populate truth for the Review step. Non-blocking — the
          // user is already on Posting; a failure just leaves truth to be
          // (re)loaded when they navigate.
          extractTruth()
            .then((truth) => alive && dispatch({ type: "setTruth", truth }))
            .catch(() => {});
        }
      })
      .catch(() => alive && dispatch({ type: "setBootstrap", bootstrap: "upload" }));
    return () => {
      alive = false;
    };
  }, []);

  const api = useMemo<WizardApi>(
    () => ({
      ...state,
      setTruth: (truth) => dispatch({ type: "setTruth", truth }),
      setPosting: (posting) => dispatch({ type: "setPosting", posting }),
      setTailor: (result) => dispatch({ type: "setTailor", result }),
      setApproval: (id, approved) =>
        dispatch({ type: "setApproval", id, approved }),
      setEdit: (id, claim) => dispatch({ type: "setEdit", id, claim }),
      setDecision: (claimId, choice) =>
        dispatch({ type: "setDecision", claimId, choice }),
      setRender: (result) => dispatch({ type: "setRender", result }),
      setCoverLetter: (result) => dispatch({ type: "setCoverLetter", result }),
      run,
    }),
    [state, run],
  );

  return <WizardContext.Provider value={api}>{children}</WizardContext.Provider>;
}

export function useWizard(): WizardApi {
  const ctx = useContext(WizardContext);
  if (!ctx) throw new Error("useWizard must be used within WizardProvider");
  return ctx;
}
