/** Domain types shared across the wizard, matching the API contract. */

/** Where a fact came from — the provenance the whole UI is built around. */
export type TruthSource = "linkedin-pdf" | "user-confirmed";

/** One achievement line, owned by an experience. */
export interface Bullet {
  id: string;
  value: string;
  source: TruthSource;
}

/** One job: role, company, date range, and its bullets. */
export interface Experience {
  id: string;
  role: string;
  company: string;
  start: string;
  end: string;
  source: TruthSource;
  bullets: Bullet[];
}

/** One qualification: degree, school, date range. */
export interface Education {
  id: string;
  degree: string;
  school: string;
  start: string;
  end: string;
  source: TruthSource;
}

/** A standalone skill — the one flat kind. */
export interface Skill {
  id: string;
  value: string;
  source: TruthSource;
}

/** A labelled profile link (e.g. LinkedIn, portfolio). */
export interface ProfileLink {
  label: string;
  url: string;
}

/** The personal header. Identity fields (name, contact, links) are yours to set
 * freely; the summary is a claim checked against your truth at render. */
export interface Profile {
  name: string;
  email: string;
  phone: string;
  location: string;
  links: ProfileLink[];
  summary: string;
}

/** The whole truth record: grouped experiences and education, flat skills, and
 * the personal header. */
export interface TruthDoc {
  experiences: Experience[];
  education: Education[];
  skills: Skill[];
  profile: Profile;
}

/** A claim tailoring wants to add that is not yet in the truth file. */
export interface Inference {
  id: string;
  claim: string;
  rationale: string;
  /** The experience this claim would attach to if confirmed. */
  experienceId: string;
}

/** An approved inference the user is confirming, carrying its (possibly
 * edited) claim text and the experience it should attach to. */
export interface ApprovedInference {
  id: string;
  claim: string;
  experienceId: string;
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

/** A whole draft bullet/line the guardrail couldn't trace, offered for approve/deny. */
export interface BlockedClaim {
  claimId: string;
  /** The draft block (experience id, or "skills") this claim came from. */
  experienceId: string;
  text: string;
  /** The specific words that couldn't be traced to the truth file. */
  tokens: string[];
}

/** Render-scoped decisions on blocked claims. Never persisted to the truth file. */
export interface RenderApprovals {
  approvedClaimIds: string[];
  deniedClaimIds: string[];
}

/** Result of rendering. If blocked, the guardrail found unverifiable claims. */
export interface RenderResult {
  blocked: boolean;
  /** Facts the guardrail could not trace to the truth file (when blocked). */
  unverifiable: string[];
  /** Whole flagged claims, each approvable/deniable on the download step. */
  blockedClaims: BlockedClaim[];
  atsWarnings: AtsWarning[];
  pdfUrl: string | null;
  docxUrl: string | null;
  /** The rendered CV HTML source, so the download step can offer an editor. */
  html: string | null;
  /** True when attached to an application and the source was saved, but no
   * PDF/DOCX could be produced (render backend unavailable). Not a failure. */
  renderUnavailable?: boolean;
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

/** One selectable model, discovered live from the provider's API/SDK. */
export interface ModelInfo {
  id: string;
  label: string;
}

/** Response from POST /api/models. */
export interface ModelList {
  models: ModelInfo[];
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

/** Generation-scoped decisions on blocked cover-letter claims. Approved claims
 * are allowed for that one generation only; never persisted to the truth file. */
export interface CoverLetterApprovals {
  approvedClaimIds: string[];
  deniedClaimIds: string[];
}

/** Result of generating a cover letter. Blocked when a claim is unverifiable. */
export interface CoverLetterResult {
  blocked: boolean;
  unverifiable: string[];
  /** Whole flagged claims (same shape as RenderResult), each approvable/deniable
   * on the download step instead of a loose token blob. */
  blockedClaims: BlockedClaim[];
  pdfUrl: string | null;
  docxUrl: string | null;
  /** The generated letter text, so the download step can offer an editor. */
  text: string | null;
  /** True when attached to an application and the source was saved, but no
   * PDF/DOCX could be produced (render backend unavailable). Not a failure. */
  renderUnavailable?: boolean;
}

/** One document an application owns: its saved editable source and the
 * per-application files it rendered to (download URLs, null if not produced). */
export interface ApplicationDocument {
  source: string;
  pdfUrl: string | null;
  docxUrl: string | null;
  updatedAt: string;
}

/** A tracked job application. `posting` is empty for General submissions; the
 * document fields are null until a CV/cover letter has been saved for it. */
export interface Application {
  id: string;
  company: string;
  website: string;
  applicationUrl: string;
  submitted: boolean;
  submissionType: string;
  reachedOut: boolean;
  toWho: string;
  responseReceived: boolean;
  method: string;
  posting: string;
  applicationDate: string;
  notes: string;
  cvDocument: ApplicationDocument | null;
  coverLetterDocument: ApplicationDocument | null;
  createdAt: string;
  updatedAt: string;
}

/** Editable fields the client may set when creating an application. */
export type ApplicationCreate = Partial<
  Pick<
    Application,
    | "company"
    | "website"
    | "applicationUrl"
    | "submitted"
    | "submissionType"
    | "reachedOut"
    | "toWho"
    | "responseReceived"
    | "method"
    | "posting"
    | "applicationDate"
    | "notes"
  >
>;

/** A partial patch of an application's editable fields. */
export type ApplicationUpdate = ApplicationCreate;

/** Result of saving an edited CV/cover letter. When blocked, the guardrail
 * found claims not traceable to the truth file and nothing was rendered. */
export interface SaveDocumentResult {
  blocked: boolean;
  unverifiable: string[];
  blockedClaims: BlockedClaim[];
  application: Application | null;
  /** True when the guardrail passed and the source was saved, but neither a PDF
   * nor a DOCX could be produced (render backend unavailable). Not a failure —
   * the document is attached; only its download links are missing. */
  renderUnavailable?: boolean;
}
