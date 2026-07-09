/** Domain types shared across the wizard, matching the API contract. */

export type TruthKind = "role" | "company" | "date" | "bullet" | "skill";

/** Where a fact came from — the provenance the whole UI is built around. */
export type TruthSource = "linkedin-pdf" | "user-confirmed";

/** One entry in the truth file: the single record of facts a CV may draw from. */
export interface TruthEntry {
  id: string;
  kind: TruthKind;
  value: string;
  source: TruthSource;
}

/** A claim tailoring wants to add that is not yet in the truth file. */
export interface Inference {
  id: string;
  claim: string;
  rationale: string;
}

/** Result of tailoring the truth file to a posting. */
export interface TailorResult {
  /** Keywords extracted from the posting, for context in the UI. */
  keywords: string[];
  /** Inferences the user must approve or reject before rendering. */
  inferences: Inference[];
}

/** An ATS linter finding surfaced before download. */
export interface AtsWarning {
  code: string;
  message: string;
}

/** Result of rendering. If blocked, the guardrail found unverifiable claims. */
export interface RenderResult {
  blocked: boolean;
  /** Facts the guardrail could not trace to the truth file (when blocked). */
  unverifiable: string[];
  atsWarnings: AtsWarning[];
  pdfUrl: string | null;
  docxUrl: string | null;
}

/** Which LLM provider is active. */
export type ProviderName = "anthropic" | "openai" | "ollama";

/** Non-secret settings status (raw keys are never sent to the browser). */
export interface SettingsStatus {
  encryptionAvailable: boolean;
  activeProvider: ProviderName | string;
  model: string;
  anthropicKeySet: boolean;
  openaiKeySet: boolean;
  ollamaHost: string;
}

/** A settings save/test payload. Empty apiKey leaves the stored key unchanged. */
export interface SettingsUpdate {
  activeProvider: ProviderName | string;
  apiKey?: string;
  model?: string;
  ollamaHost?: string;
}

/** Result of a test-connection call. */
export interface TestResult {
  ok: boolean;
  detail: string;
}

/** Whether a previously-uploaded profile is saved server-side. */
export interface ProfileStatus {
  hasProfile: boolean;
}

/** Result of generating a cover letter. Blocked when a claim is unverifiable. */
export interface CoverLetterResult {
  blocked: boolean;
  unverifiable: string[];
  pdfUrl: string | null;
  docxUrl: string | null;
}
