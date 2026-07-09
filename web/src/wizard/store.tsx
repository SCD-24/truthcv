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
  TruthEntry,
} from "../api/types";
import { getProfile } from "../api/client";

/**
 * Shared wizard state. Holds the truth file, the posting, the inferences the
 * user is deciding on, and the render result — plus a single loading/error pair
 * that step components drive through the `run` helper so async UI is consistent.
 */
interface WizardState {
  truth: TruthEntry[];
  posting: string;
  keywords: string[];
  inferences: Inference[];
  approvals: Record<string, boolean>;
  render: RenderResult | null;
  coverLetter: CoverLetterResult | null;
  /** Whether a profile PDF is already saved server-side (skip re-upload). */
  hasProfile: boolean;
  loading: boolean;
  error: string | null;
}

const initialState: WizardState = {
  truth: [],
  posting: "",
  keywords: [],
  inferences: [],
  approvals: {},
  render: null,
  coverLetter: null,
  hasProfile: false,
  loading: false,
  error: null,
};

type Action =
  | { type: "loading" }
  | { type: "error"; error: string | null }
  | { type: "setTruth"; truth: TruthEntry[] }
  | { type: "setPosting"; posting: string }
  | { type: "setTailor"; result: TailorResult }
  | { type: "setApproval"; id: string; approved: boolean }
  | { type: "setRender"; result: RenderResult }
  | { type: "setCoverLetter"; result: CoverLetterResult }
  | { type: "setHasProfile"; hasProfile: boolean };

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
    case "setRender":
      return { ...state, render: action.result, loading: false, error: null };
    case "setCoverLetter":
      return { ...state, coverLetter: action.result };
    case "setHasProfile":
      return { ...state, hasProfile: action.hasProfile };
    default:
      return state;
  }
}

interface WizardApi extends WizardState {
  setTruth: (truth: TruthEntry[]) => void;
  setPosting: (posting: string) => void;
  setTailor: (result: TailorResult) => void;
  setApproval: (id: string, approved: boolean) => void;
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

  // On load, learn whether a profile PDF is already saved so Upload can offer
  // to skip straight past re-uploading. Best-effort: failure just means "no".
  useEffect(() => {
    let alive = true;
    getProfile()
      .then((p) => alive && dispatch({ type: "setHasProfile", hasProfile: p.hasProfile }))
      .catch(() => {
        /* treat as no saved profile */
      });
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
