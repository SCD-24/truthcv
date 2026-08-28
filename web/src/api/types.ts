/** Domain types shared across the wizard, matching the API contract. */

/** Where a fact came from — the provenance the whole UI is built around. */
export type TruthSource = "uploaded-cv" | "linkedin-pdf" | "user-confirmed";

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

/** First-run onboarding progress: provider setup, profile, CV review, tour. */
export interface OnboardingState {
  providerDone: boolean;
  hasProfile: boolean;
  cvReviewedAt: string | null;
  tourSeenAt: string | null;
  complete: boolean;
}

/** Partial PUT /api/onboarding body — only the sent fields are merged. */
export interface OnboardingUpdate {
  cvReviewedAt?: string | null;
  tourSeenAt?: string | null;
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
  /** Effort levels this model supports (e.g. "low" | "medium" | "high").
   * Empty means the model has no effort concept and no effort select is shown. */
  effortLevels?: string[];
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

/** The canonical ATS form answers the unattended application agent types into
 * job application forms on the user's behalf. */
/** Answers to ATS screening questions, also used as allowed claim sources for the
 * cover-letter writer. Feed the unattended application agent and provide facts
 * the letter may reference without being blocked by the guardrail. */
export interface ProfileAnswers {
  phone: string;
  workAuthorisation: string;
  noticePeriod: string;
  locationPreference: string;
  canonicalCvAssetId: string | null;
  name: string;
  email: string;
  linkedin: string;
  github: string;
  website: string;
  requiresSponsorship: string;
  /** Neutral, country-agnostic work-authorisation note. Supersedes
   * authorizedNonGermanCountry (still accepted for one release). */
  workAuthorisationNote: string;
  /** DEPRECATED legacy key, kept so an un-migrated client still round-trips. */
  authorizedNonGermanCountry: string;
  languages: string;
  highestRelevantDegree: string;
  otherDegree: string;
  csDegree: string;
  gpa: string;
  gender: string;
  yearsOfExperience: string;
  currentRole: string;
  howDidYouHear: string;
}

/** A partial patch of the canonical answers; the PUT route merges only the
 * keys you send. */
export type ProfileAnswersUpdate = Partial<ProfileAnswers>;

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

/** One form field as the agent actually submitted it, with its provenance. */
export interface FieldSubmitted {
  label: string;
  value: string;
  source: string;
}

/** Evidence that a submission actually went through. */
export interface ApplicationConfirmation {
  text: string;
  confirmedAt: string;
  evidence: string;
}

/** One file the agent actually uploaded with the application. */
export interface ApplicationAttachment {
  kind: string;
  path: string;
}

/** The pre-application filter verdicts recorded on a tracked application.
 * These are facts about a POSTING, not a company — company-level claims
 * (employing entity, employer-review figures) live in CompanyFinding /
 * companyresearch instead, where they carry a source and an as-of date. */
export interface ApplicationScreening {
  remote: string;
  salary: string;
  language: string;
  roleType: string;
}

/** One sourced, dated company research finding. Immutable once written —
 * only `resolution`/`resolvedAt`/`resolutionNote` are ever set afterwards. */
export interface CompanyFinding {
  id: string;
  company: string;
  claim: string;
  value: string;
  sourceUrl: string;
  sourceClass: string;
  /** The date the SOURCE is dated. Empty means unknown — never substitute
   * observedAt or "today" for it. */
  asOf: string;
  observedAt: string;
  recordedBy: string;
  note: string;
  contradicts: string[];
  resolution: string;
  resolvedAt: string;
  resolutionNote: string;
}

/** One claim with two or more disagreeing, cited findings. */
export interface ContradictionGroup {
  claim: string;
  findings: CompanyFinding[];
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
  status: string;
  notes: string;
  cvDocument: ApplicationDocument | null;
  coverLetterDocument: ApplicationDocument | null;
  createdAt: string;
  updatedAt: string;
  fieldsSubmitted?: FieldSubmitted[];
  confirmation?: ApplicationConfirmation;
  screening?: ApplicationScreening;
  attachments?: ApplicationAttachment[];
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
    | "status"
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

/** Whether a company (optionally narrowed by role) is currently in cooldown. */
export interface CooldownStatus {
  inCooldown: boolean;
  expires: string | null;
  blocked: boolean;
  /** Which cooldown window produced the block: "same_role" (same company and
   * substantially the same role) or "same_company" (any role at the company).
   * null when not in cooldown or blocked via the blocklist. */
  window: "same_role" | "same_company" | null;
}

/** A job the unattended application agent screened and rejected (or otherwise
 * decided on), recording why and — for a rejection — how long the company
 * stays in cooldown before the agent will reconsider it. */
export interface ScreeningRecord {
  id: string;
  company: string;
  role: string;
  url: string;
  screenedDate: string;
  verdict: string;
  failingCriterion: string;
  reason: string;
  /** ISO timestamp the cooldown lapses; empty when there is no cooldown. */
  cooldownExpires: string;
  /** Which cooldown window produced this block, when the agent recorded one
   * from check_cooldown's response ("same_role" | "same_company"); null when
   * unknown (older records) or the block came from the blocklist. */
  cooldownWindow?: "same_role" | "same_company" | null;
  source: string;
  /** The posting as the agent read it, captured for drafting the letter later. */
  postingText: string;
  /** The employer's publication date; empty when unknown (many boards omit it). */
  postedDate: string;
  /** "" when this record is not an approval item. */
  approval: "" | "pending" | "approved" | "rejected" | "applied";
  applyAttempts: number;
  applyError: string;
  /** Why the agent could not read the posting at all — distinct from a
   * verdict on its merits. "" means no blocker. A strict union (unlike
   * `verdict` above, which is loose) so a typo is caught at compile time. */
  screeningBlocker: "" | "login_required" | "unreadable" | "not_found" | "expired";
  /** Lease state granted by the agent's hand-out call, not agent-editable.
   * An empty or past claimExpiresAt means the item is unclaimed. */
  claimedByRun: string;
  claimExpiresAt: string;
  createdAt: string;
  updatedAt: string;
}

/** One execution of the unattended job-application agent — its identity, how
 * it ended, and an honest summary of how much of the work it covered. */
export interface RunRecord {
  id: string;
  startedAt: string;
  finishedAt: string;
  status: "running" | "completed" | "cancelled" | "failed" | "";
  trigger: string;
  /** The per-run application cap in effect; 0 means uncapped. */
  applyCap: number;
  postingsSeen: number;
  screeningsRecorded: number;
  blockedCount: number;
  applicationsSubmitted: number;
  /** How many of the run's screenings landed in the operator's approval queue
   * — the outcome number for a SEMI-AUTO run, which submits nothing by
   * design and so would otherwise have no number describing what it did. */
  queuedForApproval: number;
  /** Submissions that arrived for an item this run had not claimed — flagged,
   * not refused. */
  overCapWrites: number;
  /** Where a partial run stopped, in the agent's own words. Empty for a run
   * that completed normally. */
  stoppedReason: string;
  note: string;
}

/** One page of runs from GET /api/runs, newest first. `total` counts every
 * recorded run, not this page — it is what tells the caller how many pages
 * exist, and it cannot be derived from a capped page. */
export interface RunPage {
  runs: RunRecord[];
  total: number;
  limit: number;
  offset: number;
}

/** A screening's current cover letter. `source` says whether the guardrail
 * vouches for the text: "generated" is what the model wrote and the guardrail
 * validated, "operator" is text you wrote, saved verbatim and unvalidated. */
export interface CoverLetterDraft {
  text: string;
  paragraphs: Record<string, unknown>[];
  source: "generated" | "operator";
  updatedAt: string;
}

/** Job search profile with search criteria and requirements. */
export interface JobProfile {
  name: string;
  enabled: boolean;
  keywords: string[];
  locations: string[];
  remoteModel: string | null;
  employmentCountry: string | null;
  eorAllowed: boolean | null;
  requireEntityVerification: boolean;
  salaryFloor: number | null;
  salaryAskMin: number | null;
  salaryAskMax: number | null;
  /** Currency the salary band is expressed in. Not editable in the UI yet, but
   * round-tripped through save so a hand-set value is never silently reset. */
  /** User-chosen currency code; null means not configured — no regional
   * default exists, and display renders "not configured" instead. */
  currency: string | null;
  workingLanguage: string | null;
  glassdoorMin: number | null;
  glassdoorMinReviews: number | null;
  acceptedRoleTypes: string[];
  rejectedRoleTypes: string[];
}

/** One job board the agent searches AND a site you sign in to.
 *
 * `source`/`signinUrl` are the operator's stored input (an override, if
 * set). `domain`, `effectiveSigninUrl` and `isDefault` are resolved
 * server-side (like `companyBoards` on `AgentConfig`, readonly): `isDefault`
 * means the board is always searched and cannot be removed, `isApi` means the
 * board is pulled from over its HTTP API with a saved key instead of being
 * signed in to in a browser — `effectiveSigninUrl` is always "" for those. */
export interface JobBoard {
  source: string;
  signinUrl: string;
  readonly domain: string;
  readonly effectiveSigninUrl: string;
  readonly isDefault: boolean;
  readonly isApi: boolean;
}

/** Whether an API-backed board has a key saved. The key is never returned. */
export interface JobBoardKeyStatus {
  source: string;
  keySet: boolean;
  /** False when ENCRYPTION_KEY is unset — the key cannot be saved at all. */
  encryptionAvailable: boolean;
}

/** Resolved company board entry. */
export interface CompanyBoard {
  company: string;
  careersUrl: string;
  ats: string;
  status: string;
  resolvedAt: string;
}

/** Running/idle status returned by the agent supervisor control server. */
export interface AgentStatus {
  running: boolean;
  /** True between a cancel request and the run's exit — the run is stopping,
   * not still working. */
  cancelling: boolean;
  lastStartedAt: string | null;
  lastFinishedAt: string | null;
  lastExitCode: number | null;
  /** The last run ended because it was cancelled. Its non-zero exit code is
   * expected, so it must not be reported as a failure. */
  lastCancelled: boolean;
}

/** Result of triggering a run via POST /api/agent/run. */
export interface AgentRunResult {
  started: boolean;
  running: boolean;
}

/** Result of stopping a run via POST /api/agent/cancel. `cancelled` is false
 * when there was nothing to cancel or a cancel was already under way. */
export interface AgentCancelResult {
  cancelled: boolean;
  running: boolean;
}

/** Configuration for the unattended job application agent. */
export interface AgentConfig {
  /** Autonomy: "off" runs nothing, "semi" queues what passes for approval,
   * "full" applies on its own. `enabled` is derived from this server-side and
   * is read-only. */
  mode: "off" | "semi" | "full";
  enabled: boolean;
  blockedCompanies: string[];
  runAt: string[];
  runDays: string[];
  profiles: JobProfile[];
  jobBoards: JobBoard[];
  targetCompanies: string[];
  cooldownDays: number | null;
  /** Per-window overrides; null inherits the legacy single cooldownDays. */
  cooldownDaysSameRole: number | null;
  cooldownDaysSameCompany: number | null;
  maxApplicationsPerRun: number | null;
  /** Discovery freshness window in days: only consider postings published
   * within this many days. null leaves it unset (the historical past-week
   * search filter); 0 disables the window entirely. */
  maxPostingAgeDays: number | null;
  readonly companyBoards: CompanyBoard[];
}

/** A partial patch of agent configuration; the PUT route merges only the
 * keys you send. Limited to what PUT /api/agent/config actually accepts
 * (api/schemas.py AgentConfigUpdate) — `enabled` is derived server-side and
 * `companyBoards` is resolved server-side, so both 422 if sent. */
export type AgentConfigUpdate = Partial<
  Pick<
    AgentConfig,
    | "mode"
    | "blockedCompanies"
    | "runAt"
    | "runDays"
    | "profiles"
    | "jobBoards"
    | "targetCompanies"
    | "cooldownDays"
    | "cooldownDaysSameRole"
    | "cooldownDaysSameCompany"
    | "maxApplicationsPerRun"
    | "maxPostingAgeDays"
  >
>;

/** Provider identifier for connection status and routing. */
export type CardKey = "claude" | "codex" | "openrouter" | "ollama";

/** The mode literals the backend catalog emits (connections/catalog.py CARDS).
 * The single source of truth for what a mode string can be — fixtures and
 * checks derive from this rather than hand-typing "apikey"/"url" elsewhere. */
export const CONNECTION_MODES = ["subscription", "apikey", "url"] as const;
export type ConnectionMode = (typeof CONNECTION_MODES)[number];

/** Status of a single provider connection. */
export interface ConnectionStatus {
  provider: CardKey | string;
  label: string;
  modes: ConnectionMode[];
  subscriptionConnected: boolean;
  apiKeyConnected: boolean;
  authMode: string;
  expiresAt: number | null;
  connectedAt: number | null;
}

/** Response from GET /api/auth/status. */
export interface ConnectionList {
  encryptionAvailable: boolean;
  connections: ConnectionStatus[];
}

/** Result of starting a login flow for a provider. */
export interface StartLoginResult {
  flow: "paste-code" | "browser" | "device-code" | string;
  authUrl?: string | null;
  userCode?: string | null;
  verificationUri?: string | null;
}

/** A routing choice for a task or agent — which model via which provider. */
export interface RouteChoice {
  connection: string;
  model: string;
  /** Chosen effort level for models that support it; omit or "" for provider default. */
  effort?: string;
}

/** Routing configuration for tasks and defaults. */
export interface Routing {
  tasks: Record<string, RouteChoice>;
  agent: RouteChoice | null;
  default: RouteChoice | null;
}

/** Partial PUT /api/routing body. A task entry (or `agent`/`default`) sent
 * explicitly as `null` clears that route rather than leaving it unchanged —
 * mirrors RoutingUpdate in api/schemas.py, which is why this isn't just
 * `Partial<Routing>`: `Routing.tasks` values are never null. */
export interface RoutingUpdate {
  tasks?: Record<string, RouteChoice | null>;
  agent?: RouteChoice | null;
  default?: RouteChoice | null;
}

/** One host the agent could not get past a sign-in wall on. */
export type SigninQueueSite = {
  host: string;
  signinUrl: string;
  waiting: number;
  lastBlockedAt: string;
  companies: string[];
};

export type SigninQueue = { sites: SigninQueueSite[] };

/** State of the attended sign-in session, if one is open. */
export type BrowserSession = {
  open: boolean;
  url: string | null;
  startedAt: string | null;
  evictDeadline: string | null;
};
