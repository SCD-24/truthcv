import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useReducer,
  type ReactNode,
} from "react";
import type { OnboardingState, TruthDoc } from "../api/types";

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
  hobbies: [],
  profile: emptyProfile,
};
import { extractTruth, getOnboarding } from "../api/client";

/**
 * Startup gate for the app shell.
 * - "pending": still checking onboarding state (show a splash, not the shell)
 * - "ready": onboarding state resolved — render the shell.
 * - "error": the onboarding check failed — show a retry screen, never guess.
 */
export type Bootstrap = "pending" | "ready" | "error";

/**
 * Shared wizard state. Holds the truth file and the current posting draft
 * (read by DocumentEditor and the CV upload/review flow), plus a single
 * loading/error pair that step components drive through the `run` helper so
 * async UI is consistent. Per-generation state (inferences, approvals,
 * render/cover-letter results) now lives locally in ManualPage, which owns
 * the whole generate-and-attach flow for a single posting.
 */
interface WizardState {
  truth: TruthDoc;
  posting: string;
  /** Whether a profile PDF is already saved server-side (skip re-upload). */
  hasProfile: boolean;
  /** First-run onboarding progress fetched at startup (null until resolved). */
  onboarding: OnboardingState | null;
  /** Resolved startup gate; "ready" once onboarding state is known. */
  bootstrap: Bootstrap;
  loading: boolean;
  error: string | null;
}

const initialState: WizardState = {
  truth: emptyTruth,
  posting: "",
  hasProfile: false,
  onboarding: null,
  bootstrap: "pending",
  loading: false,
  error: null,
};

type Action =
  | { type: "loading" }
  | { type: "error"; error: string | null }
  | { type: "setTruth"; truth: TruthDoc }
  | { type: "setPosting"; posting: string }
  | { type: "setHasProfile"; hasProfile: boolean }
  | { type: "setOnboarding"; onboarding: OnboardingState | null }
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
    case "setHasProfile":
      return { ...state, hasProfile: action.hasProfile };
    case "setOnboarding":
      return { ...state, onboarding: action.onboarding };
    case "setBootstrap":
      return { ...state, bootstrap: action.bootstrap };
    default:
      return state;
  }
}

interface WizardApi extends WizardState {
  setTruth: (truth: TruthDoc) => void;
  setPosting: (posting: string) => void;
  /** Replace the onboarding state (e.g. after an updateOnboarding() call). */
  setOnboarding: (onboarding: OnboardingState | null) => void;
  /** Run an async task, driving loading/error and returning its result or null. */
  run: <T>(fn: () => Promise<T>) => Promise<T | null>;
  /** Re-run the startup onboarding check after it failed (bootstrap === "error"). */
  retryBootstrap: () => void;
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

  // On load, resolve onboarding state — this gates the boot splash. Whether
  // onboarding is complete is a fact only the backend has, so a failed check
  // must never be guessed at: it flips to "error" and shows a retry screen
  // instead of the shell. When a profile already exists we populate truth in
  // the background: the extract is free when the source is unchanged, so
  // returning users skip re-upload without re-spending tokens, and a
  // slow/failed extract surfaces on the page it feeds (never as a stuck
  // splash).
  const loadBootstrap = useCallback(() => {
    let alive = true;
    dispatch({ type: "setBootstrap", bootstrap: "pending" });
    const settle = (onboarding: OnboardingState) => {
      if (!alive) return;
      dispatch({ type: "setOnboarding", onboarding });
      dispatch({ type: "setHasProfile", hasProfile: onboarding.hasProfile });
      dispatch({ type: "setBootstrap", bootstrap: "ready" });
      if (onboarding.hasProfile) {
        // Background: populate truth for the Review step. Non-blocking — a
        // failure just leaves truth to be (re)loaded when it's needed.
        extractTruth()
          .then((truth) => alive && dispatch({ type: "setTruth", truth }))
          .catch(() => {});
      }
    };
    getOnboarding()
      .then(settle)
      .catch(() => {
        if (!alive) return;
        dispatch({ type: "setBootstrap", bootstrap: "error" });
      });
    return () => {
      alive = false;
    };
  }, []);

  useEffect(() => loadBootstrap(), [loadBootstrap]);

  const api = useMemo<WizardApi>(
    () => ({
      ...state,
      setTruth: (truth) => dispatch({ type: "setTruth", truth }),
      setPosting: (posting) => dispatch({ type: "setPosting", posting }),
      setOnboarding: (onboarding) => dispatch({ type: "setOnboarding", onboarding }),
      run,
      retryBootstrap: () => loadBootstrap(),
    }),
    [state, run, loadBootstrap],
  );

  return <WizardContext.Provider value={api}>{children}</WizardContext.Provider>;
}

export function useWizard(): WizardApi {
  const ctx = useContext(WizardContext);
  if (!ctx) throw new Error("useWizard must be used within WizardProvider");
  return ctx;
}
