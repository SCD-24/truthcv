import type {
  ApprovedInference,
  TruthDoc,
  TailorResult,
  RenderApprovals,
  RenderResult,
  ModelInfo,
  ModelList,
  SettingsStatus,
  SettingsUpdate,
  TestResult,
  ProfileStatus,
  OnboardingState,
  OnboardingUpdate,
  ProfileAnswers,
  ProfileAnswersUpdate,
  CoverLetterResult,
  CoverLetterApprovals,
  BlockedClaim,
  Application,
  ApplicationCreate,
  ApplicationPage,
  ApplicationSortKey,
  ApplicationUpdate,
  SaveDocumentResult,
  ScreeningRecord,
  CoverLetterDraft,
  CooldownStatus,
  AgentConfig,
  AgentConfigUpdate,
  AgentStatus,
  AgentRunResult,
  AgentCancelResult,
  ConnectionStatus,
  ConnectionList,
  StartLoginResult,
  PollLoginResult,
  Routing,
  RoutingUpdate,
  RunStopResult,
  SigninQueue,
  JobBoardKeyStatus,
  BrowserSession,
  CompanyFinding,
  ContradictionGroup,
  RunPage,
  RunRecord,
} from "./types";
import { errorDetailToMessage } from "./errorDetail";

/** One reusable text block for the LLM prompt library, slotted into a preset. */
export interface PromptFragment {
  id: string;
  slot: string;
  title: string;
  text: string;
  seeded: boolean;
  conflictsWith: string[];
}

/** A named, ordered set of prompt fragments; one preset can be the default. */
export interface PromptPreset {
  id: string;
  name: string;
  fragmentIds: string[];
  isDefault: boolean;
  seeded: boolean;
}

/** A conflict found among a preset's fragments — two fragments claiming the
 * same exclusive slot, a fragment declaring a conflict with another, or a
 * fragment id that doesn't exist. */
export interface PromptConflict {
  kind: "exclusive_slot" | "declared" | "unknown_fragment";
  fragmentIds: string[];
  slot: string | null;
  message: string;
}

/**
 * Typed wrappers over the wizard's REST routes. Served same-origin by the API
 * (dev proxies /api to the backend), so the base is empty. Every wrapper throws
 * an Error with an actionable, user-facing message when the request fails — the
 * step components surface that message directly.
 */

/** Requests abort after this long so a hung backend never freezes the UI.
 * LLM-backed routes (tailor runs two sequential model calls) routinely take
 * 30s+, so this must comfortably exceed real model latency — otherwise a slow
 * but healthy call aborts and is misreported as an unreachable server. */
const REQUEST_TIMEOUT_MS = 120_000;

/** Thrown by request() instead of a plain Error when a 422's detail carries
 * blockedClaims — i.e. the truthfulness guardrail blocked a generation. Carries
 * the structured data (claims, the paragraphs that were validated, and the
 * block reason) a caller needs to offer an approve/deny UI, while `message`
 * stays exactly what a plain Error would have said, so any caller that only
 * reads `.message` is unaffected by this type existing. */
export class GuardrailBlockedError extends Error {
  claims: BlockedClaim[];
  paragraphs: unknown[];
  blockedReason: string;

  constructor(message: string, claims: BlockedClaim[], paragraphs: unknown[], blockedReason: string) {
    super(message);
    this.name = "GuardrailBlockedError";
    this.claims = claims;
    this.paragraphs = paragraphs;
    this.blockedReason = blockedReason;
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), REQUEST_TIMEOUT_MS);
  let res: Response;
  try {
    res = await fetch(path, { ...init, signal: controller.signal });
  } catch {
    // An abort (our timeout) is distinct from a genuine connection failure —
    // reporting a slow model call as "server down" sends the user chasing the
    // wrong problem.
    throw new Error(
      controller.signal.aborted
        ? "The server took too long to respond. It may still be working — wait a moment and try again."
        : "Can't reach the server. Check that TruthCV is running, then try again.",
    );
  } finally {
    clearTimeout(timer);
  }
  if (!res.ok) {
    const body: unknown = await res.json().catch(() => undefined);
    const message = errorDetailToMessage(body) || `That didn't work (error ${res.status}). Try again.`;
    const detail =
      body !== null && typeof body === "object" && "detail" in body
        ? (body as { detail: unknown }).detail
        : undefined;
    if (
      detail !== null &&
      typeof detail === "object" &&
      Array.isArray((detail as { blockedClaims?: unknown }).blockedClaims) &&
      (detail as { blockedClaims: unknown[] }).blockedClaims.length > 0
    ) {
      const d = detail as {
        blockedClaims: BlockedClaim[];
        paragraphs?: unknown[];
        blockedReason?: string;
      };
      throw new GuardrailBlockedError(message, d.blockedClaims, d.paragraphs ?? [], d.blockedReason ?? "");
    }
    throw new Error(message);
  }
  // Some routes (render download links) still return JSON; callers that expect
  // no body pass T = void and ignore the result.
  return res.status === 204 ? (undefined as T) : ((await res.json()) as T);
}

/** Step 1 — upload the CV file for text extraction. */
export async function uploadCv(file: File): Promise<void> {
  const body = new FormData();
  body.append("file", file);
  await request<void>("/api/upload", { method: "POST", body });
}

/** Step 1 — run structured extraction into the truth file. */
export function extractTruth(): Promise<TruthDoc> {
  return request("/api/extract", { method: "POST" });
}

/** Step 2 — load the current truth file for review. */
export function getTruth(): Promise<TruthDoc> {
  return request("/api/truth");
}

/** Step 2 — persist the user's corrections. After this, the facts are trusted. */
export function saveTruth(truth: TruthDoc): Promise<void> {
  return request<void>("/api/truth", {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(truth),
  });
}

/** Step 3 — tailor the truth file to the posting; returns inferences to confirm. */
export function tailor(posting: string): Promise<TailorResult> {
  return request("/api/tailor", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ posting }),
  });
}

/** Step 4 — confirm approved inferences; each becomes a source:user-confirmed
 * bullet. Sends the (possibly edited) claim text and target experience per
 * item, so what the user typed at Confirm is exactly what's written. */
export function confirmInferences(approved: ApprovedInference[]): Promise<void> {
  return request<void>("/api/confirm-inferences", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ approved }),
  });
}

/** Step 5 — run guardrail + ATS review and render PDF/DOCX.
 * Pass render-scoped approvals to approve/deny individually blocked claims;
 * approvals apply to this render only and never touch the truth file. */
export function render(
  approvals?: RenderApprovals,
  applicationId?: string,
): Promise<RenderResult> {
  const payload: Record<string, unknown> = {};
  if (approvals) payload.approvals = approvals;
  if (applicationId) payload.applicationId = applicationId;
  const hasBody = Object.keys(payload).length > 0;
  return request("/api/render", {
    method: "POST",
    headers: hasBody ? { "Content-Type": "application/json" } : undefined,
    body: hasBody ? JSON.stringify(payload) : undefined,
  });
}

/** Whether a profile PDF is already saved on the server. */
export function getProfile(): Promise<ProfileStatus> {
  return request("/api/profile");
}

/** First-run onboarding progress: provider setup, profile, CV review, tour. */
export function getOnboarding(): Promise<OnboardingState> {
  return request("/api/onboarding");
}

/** Patch onboarding progress (only the keys you pass change). Returns fresh values. */
export function updateOnboarding(patch: OnboardingUpdate): Promise<OnboardingState> {
  return request("/api/onboarding", {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(patch),
  });
}

/** Read the canonical ATS form answers the application agent submits. */
export function getProfileAnswers(): Promise<ProfileAnswers> {
  return request("/api/profile/answers");
}

/** Patch the canonical answers (only the keys you pass change). Returns fresh values. */
export function saveProfileAnswers(body: ProfileAnswersUpdate): Promise<ProfileAnswers> {
  return request("/api/profile/answers", {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
}

/** Read non-secret provider settings status. */
export function getSettings(): Promise<SettingsStatus> {
  return request("/api/settings");
}

/** Save provider settings (encrypted at rest). Returns fresh status. */
export function saveSettings(body: SettingsUpdate): Promise<SettingsStatus> {
  return request("/api/settings", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
}

/** List the selected provider's models, pulled live from its API/SDK. Uses a
 * typed-but-unsaved key/host if present, else the saved credential. */
export function listModels(body: SettingsUpdate): Promise<ModelInfo[]> {
  return request<ModelList>("/api/models", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  }).then((r) => r.models);
}

/** Test the provider connection with saved/submitted credentials. */
export function testConnection(body: SettingsUpdate): Promise<TestResult> {
  return request("/api/settings/test", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
}

/** Generate a guardrail-truthful cover letter for the current posting.
 * Pass generation-scoped approvals to approve/deny individually blocked claims;
 * approvals apply to this generation only and never touch the truth file. */
export function generateCoverLetter(
  tone: string,
  length: string,
  approvals?: CoverLetterApprovals,
  applicationId?: string,
  posting?: string,
  presetId?: string,
): Promise<CoverLetterResult> {
  return request("/api/cover-letter", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ tone, length, approvals, applicationId, posting, presetId }),
  });
}

/** Every tracked job application, most recent first. When `q` is a non-blank
 * search string, filters to applications matching it server-side. */
export function listApplications(q = ""): Promise<Application[]> {
  if (q.trim()) {
    const params = new URLSearchParams({ q });
    return request(`/api/applications?${params}`);
  }
  return request("/api/applications");
}

/** One page of applications, sorted by the given key and direction. A
 * non-blank `q` filters server-side (same fields as `listApplications`)
 * before paging, so the page's `total` is the match count. */
export function listApplicationsPage(opts: {
  limit?: number;
  offset?: number;
  sort?: ApplicationSortKey;
  direction?: "asc" | "desc";
  q?: string;
}): Promise<ApplicationPage> {
  const params = new URLSearchParams();
  if (opts.limit !== undefined) params.set("limit", String(opts.limit));
  if (opts.offset !== undefined) params.set("offset", String(opts.offset));
  if (opts.sort) params.set("sort", opts.sort);
  if (opts.direction) params.set("direction", opts.direction);
  if (opts.q && opts.q.trim()) params.set("q", opts.q);
  const qs = params.toString();
  return request<ApplicationPage>(`/api/applications/page${qs ? `?${qs}` : ""}`);
}

/** Create a new application record from user-entered fields. */
export function createApplication(body: ApplicationCreate): Promise<Application> {
  return request("/api/applications", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
}

/** Patch an application's editable fields (only the ones you pass change). */
export function updateApplication(
  id: string,
  body: ApplicationUpdate,
): Promise<Application> {
  return request(`/api/applications/${id}`, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
}

/** Delete an application and the CV/cover-letter files it owns. */
export function deleteApplication(id: string): Promise<void> {
  return request<void>(`/api/applications/${id}`, { method: "DELETE" });
}

/**
 * URL for the applications export (a CSV of the table plus each application's
 * documents in per-company folders, zipped). It is a plain browser navigation,
 * not a fetch: the backend sets Content-Disposition so the browser downloads
 * the zip directly, avoiding holding the whole archive in memory as a blob.
 */
export const APPLICATIONS_EXPORT_URL = "/api/applications/export";

/** Save edited CV HTML onto an application: guardrail-checked, then rendered.
 * A blocked result means an edit strayed from the truth file — nothing saved. */
export function saveApplicationCv(
  id: string,
  html: string,
): Promise<SaveDocumentResult> {
  return request(`/api/applications/${id}/cv`, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ html }),
  });
}

/** Save edited cover-letter text onto an application (guardrail-checked). */
export function saveApplicationCoverLetter(
  id: string,
  text: string,
): Promise<SaveDocumentResult> {
  return request(`/api/applications/${id}/cover-letter`, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ text }),
  });
}

/** Every job the application agent has screened, most recent first — the
 * record of what it rejected (and why) and what stays in cooldown. */
export function listScreenings(): Promise<ScreeningRecord[]> {
  return request("/api/screenings");
}

/** Delete a screening record, ending its cooldown and un-blocking the target. */
export function deleteScreening(id: string): Promise<void> {
  return request<void>("/api/screenings/" + encodeURIComponent(id), {
    method: "DELETE",
  });
}

/** Record that the operator applied to this posting themselves: creates the
 * Applications row and retires the queue item. 409 if it was already applied. */
export function markScreeningApplied(id: string): Promise<Application> {
  return request("/api/screenings/" + encodeURIComponent(id) + "/applied", {
    method: "POST",
  });
}

/** The approval queue: screenings the agent deferred and is waiting on. */
export function listPendingApprovals(): Promise<ScreeningRecord[]> {
  return request("/api/screenings?approval=pending");
}

/** Approved but not yet applied — kept visible so repeated failures are noticed. */
export function listApprovedApplications(): Promise<ScreeningRecord[]> {
  return request("/api/screenings?approval=approved");
}

/** Postings you rejected. Kept listed so a decision can be reversed. */
export function listRejectedApprovals(): Promise<ScreeningRecord[]> {
  return request("/api/screenings?approval=rejected");
}

/** Every sourced company research finding, newest observed first. */
export function listCompanyFindings(): Promise<CompanyFinding[]> {
  return request("/api/company-findings");
}

/** Every finding recorded for one company. */
export function listCompanyFindingsFor(company: string): Promise<CompanyFinding[]> {
  return request("/api/company-findings/" + encodeURIComponent(company));
}

/** Open contradiction groups; narrowed to one company, or across all of them. */
export function listContradictions(company?: string): Promise<ContradictionGroup[]> {
  const query = company ? `?company=${encodeURIComponent(company)}` : "";
  return request(`/api/company-findings/contradictions${query}`);
}

/** Record an operator-sourced company finding. Never overwrites an existing one. */
export function createCompanyFinding(body: {
  company: string;
  claim: string;
  value: string;
  sourceUrl: string;
  sourceClass: string;
  asOf?: string;
  note?: string;
}): Promise<CompanyFinding> {
  return request("/api/company-findings", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
}

/** Accept or reject an existing finding. Cannot change its factual fields. */
export function resolveCompanyFinding(
  id: string,
  resolution: string,
  note?: string,
): Promise<CompanyFinding> {
  return request("/api/company-findings/" + encodeURIComponent(id), {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ resolution, note: note ?? "" }),
  });
}

/** Postings already applied to — the queue items that settled into tracked
 * applications. Read-only here; they are managed on the Applications page. */
export function listAppliedScreenings(): Promise<ScreeningRecord[]> {
  return request("/api/screenings?approval=applied");
}

/** Postings the agent rejected on a criterion — never queued, and reviewable
 * so a filter you disagree with does not silently lose a role. Filtered
 * client-side: an agent-criteria rejection has an empty `approval`, but so
 * does any other untouched record (`approval: str = ""` is the schema
 * default), so `?approval=` would also return records that were never
 * screened as rejected at all. */
export async function listDidNotPass(): Promise<ScreeningRecord[]> {
  const all = await listScreenings();
  // A record blocked at screening time (the agent could not read the
  // posting at all) is not a rejection on its merits — excluding it here
  // stops that fabricated outcome from ever reaching this list.
  return all.filter((s) => s.verdict === "rejected" && !s.approval && !s.screeningBlocker);
}

/** Record the operator's decision on one screening. */
export function setScreeningApproval(
  id: string,
  approval: "approved" | "rejected" | "pending",
): Promise<ScreeningRecord> {
  return request("/api/screenings/" + encodeURIComponent(id), {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ approval }),
  });
}

/** Set or correct a posting's URL — used both to supply the URL a historical
 * import left blank and to edit a URL that already has a value. */
export function setScreeningUrl(id: string, url: string): Promise<ScreeningRecord> {
  return request("/api/screenings/" + encodeURIComponent(id), {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ url }),
  });
}

/** Correct a screening's job title — used both to fill a role a historical
 * import left blank and to fix a garbled one. The server rejects an unusable
 * title (empty, placeholder text, a URL, too long) with a 422. */
export function setScreeningRole(id: string, role: string): Promise<ScreeningRecord> {
  return request("/api/screenings/" + encodeURIComponent(id), {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ role }),
  });
}

/** Supply the posting text a record was created without. */
export function setScreeningPostingText(
  id: string,
  postingText: string,
): Promise<ScreeningRecord> {
  return request("/api/screenings/" + encodeURIComponent(id), {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ postingText }),
  });
}

/** The stored draft, or null when none has been generated yet.
 *
 * `request`'s errors are plain `Error`s carrying only a message (see its
 * definition above) — no status code survives the throw. The 404 route
 * (api/routes.py get_screening_letter) always sends the same detail string,
 * so that string is what distinguishes "no draft yet" from a real failure. */
export async function getScreeningLetter(id: string): Promise<CoverLetterDraft | null> {
  try {
    return await request<CoverLetterDraft>(
      "/api/screenings/" + encodeURIComponent(id) + "/letter",
    );
  } catch (e) {
    if (e instanceof Error && e.message === "No cover letter drafted yet.") return null;
    throw e;
  }
}

/** Draft the letter from the stored posting text. `force` discards an edit of
 * yours; without it the server refuses to overwrite your own words.
 *
 * `approvals` carries generation-scoped decisions on claims a previous attempt
 * blocked (never persisted to truth), and `paragraphs` echoes back that
 * attempt's paragraphs so the retry re-validates the SAME letter instead of
 * paying for a second LLM call. Both are optional; omit them for a fresh
 * generation. */
export function generateScreeningLetter(
  id: string,
  opts?: { force?: boolean; approvals?: CoverLetterApprovals; paragraphs?: unknown[] },
): Promise<CoverLetterDraft> {
  return request("/api/screenings/" + encodeURIComponent(id) + "/letter", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      force: opts?.force ?? false,
      approvals: opts?.approvals,
      paragraphs: opts?.paragraphs,
    }),
  });
}

/** Save your own text. It is stored verbatim and never validated. */
export function saveScreeningLetter(id: string, text: string): Promise<CoverLetterDraft> {
  return request("/api/screenings/" + encodeURIComponent(id) + "/letter", {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ text }),
  });
}

/** One decision across many screenings; the result reports each id separately. */
export function bulkSetApproval(
  ids: string[],
  approval: "approved" | "rejected",
): Promise<{ results: { id: string; ok: boolean }[] }> {
  return request("/api/screenings/approvals", {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ ids, approval }),
  });
}

/** Delete many screening records at once; the result reports each id separately.
 * Deleting a screening ends its cooldown contribution and un-blocks that target
 * for re-screening, same as the single-record delete. */
export function bulkDeleteScreenings(
  ids: string[],
): Promise<{ results: { id: string; ok: boolean }[] }> {
  return request("/api/screenings/deletions", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ ids }),
  });
}

/** Whether `company` (optionally narrowed by `role`) is currently in cooldown. */
export function getCooldown(company: string, role?: string): Promise<CooldownStatus> {
  const params = new URLSearchParams({ company });
  if (role) params.set("role", role);
  return request(`/api/cooldown?${params.toString()}`);
}

/** Read the agent configuration. */
export function getAgentConfig(): Promise<AgentConfig> {
  return request("/api/agent/config");
}

/** Patch the agent configuration (only the keys you pass change). Returns fresh values. */
export function updateAgentConfig(body: AgentConfigUpdate): Promise<AgentConfig> {
  return request("/api/agent/config", {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
}

/** Trigger an immediate agent run. Fire-and-forget: returns before the run
 * finishes. Throws when the agent container is unreachable (503). */
export function triggerAgentRun(): Promise<AgentRunResult> {
  return request("/api/agent/run", { method: "POST" });
}

/** Stop the run in progress. Fire-and-forget: the supervisor signals the run
 * and answers immediately, so poll getAgentStatus for the transition to idle.
 * Throws when the agent container is unreachable (503). */
export function cancelAgentRun(): Promise<AgentCancelResult> {
  return request("/api/agent/cancel", { method: "POST" });
}

/** Poll the agent supervisor for running/idle status. */
export function getAgentStatus(): Promise<AgentStatus> {
  return request("/api/agent/status");
}

/** The most recently started agent runs, newest first. */
export function listRuns(limit?: number, offset?: number): Promise<RunPage> {
  const params = new URLSearchParams();
  if (limit) params.set("limit", String(limit));
  if (offset) params.set("offset", String(offset));
  const qs = params.toString();
  return request<RunPage>(`/api/runs${qs ? `?${qs}` : ""}`);
}

/** A single run record, or throws (404) if no run with this id was recorded. */
export function getRun(id: string): Promise<RunRecord> {
  return request(`/api/runs/${encodeURIComponent(id)}`);
}

/** Stop a running run: signals it through the supervisor when it is live
 * (outcome "cancelling"), or closes an orphaned record as failed when there
 * is no live supervisor to signal (outcome "closed"). Pass the run id.
 * Returns the outcome plus the updated run record. */
export function stopRun(id: string): Promise<RunStopResult> {
  return request(`/api/runs/${encodeURIComponent(id)}/stop`, { method: "POST" });
}

/** List all provider connections and their status. */
export function listConnections(): Promise<ConnectionList> {
  return request("/api/auth/status");
}

/** Start a login flow for a provider. */
export function startLogin(provider: string): Promise<StartLoginResult> {
  return request(`/api/auth/${provider}/start`, { method: "POST" });
}

/** Complete a login flow for any provider (code or device-code). */
export function completeLogin(provider: string, code: string): Promise<ConnectionStatus> {
  return request(`/api/auth/${provider}/complete`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ code }),
  });
}

/** Poll a device-code login flow for any provider. */
export function pollLogin(provider: string): Promise<PollLoginResult> {
  return request(`/api/auth/${provider}/poll`, { method: "POST" });
}

/** @deprecated Use completeLogin('claude', code) instead. Retained so call sites
 * that haven't migrated still work against the /api/auth/claude/complete alias. */
export function completeClaudeLogin(code: string): Promise<ConnectionStatus> {
  return completeLogin("claude", code);
}

/** Save an API key or base URL for a provider and fetch available models. */
export function saveConnectionKey(
  provider: string,
  body: { apiKey?: string; baseUrl?: string; bearer?: string },
): Promise<ModelInfo[]> {
  return request<ModelList>(`/api/auth/${provider}/key`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  }).then((r) => r.models);
}

/** Fetch available models for a provider connection. */
export function listConnectionModels(provider: string): Promise<ModelInfo[]> {
  return request<ModelList>(`/api/auth/${provider}/models`).then((r) => r.models);
}

/** Test the connection to a provider with an optional model. */
export function testConnectionProvider(provider: string, model?: string): Promise<TestResult> {
  return request(`/api/auth/${provider}/test`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ model: model || undefined }),
  });
}

/** Logout from a provider connection mode. */
export function logoutConnection(provider: string, mode: string): Promise<ConnectionStatus> {
  return request(`/api/auth/${provider}/logout?mode=${encodeURIComponent(mode)}`, {
    method: "POST",
  });
}

/** Fetch the current routing configuration. */
export function getRouting(): Promise<Routing> {
  return request("/api/routing");
}

/** Update the routing configuration (only the keys you pass change). */
export function updateRouting(body: RoutingUpdate): Promise<Routing> {
  return request("/api/routing", {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
}

/** Sites the agent could not get past a sign-in wall on. */
/** Whether an API-backed job board has a key saved. The key is never returned. */
export function getJobBoardKey(source: string): Promise<JobBoardKeyStatus> {
  return request(`/api/job-boards/${encodeURIComponent(source)}/key`);
}

/** Save an API-backed job board's key, or clear it by passing an empty string. */
export function saveJobBoardKey(source: string, apiKey: string): Promise<JobBoardKeyStatus> {
  return request(`/api/job-boards/${encodeURIComponent(source)}/key`, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ apiKey }),
  });
}

/** Verify the saved key with one live request against the board's API. */
export function testJobBoardKey(source: string): Promise<TestResult> {
  return request(`/api/job-boards/${encodeURIComponent(source)}/key/test`, { method: "POST" });
}

export function getSigninQueue(): Promise<SigninQueue> {
  return request("/api/browser/signin-queue");
}

/** Whether an attended sign-in session is open, and at which URL. */
export function getBrowserSession(): Promise<BrowserSession> {
  return request("/api/browser/session");
}

/** Close the attended session and release the browser. */
export function closeBrowserSession(): Promise<void> {
  return request<void>("/api/browser/session", { method: "DELETE" });
}

/** Reasons the session server can send back in a 409's `detail.reason`.
 * `errorDetailToMessage` doesn't understand this shape (it only reads
 * `detail.message` / `detail.blockedClaims`), so the raw reason is carried
 * on `BrowserSessionError` itself for the caller to map to copy. */
export type BrowserSessionRefusalReason =
  | "agent_running"
  | "session_open"
  | "profile_busy"
  | "launch_failed"
  | "probe_failed";

/** Raised by openBrowserSession so the session page can tell the three
 * outcomes apart. `request` collapses every failure into one message, which
 * is right for the wizard but wrong here: "the agent is busy" and "the
 * browser is broken" call for different words and different buttons.
 *
 * `reason` and `conflictUrl` carry the 409 body's own `{reason, url}` —
 * `errorDetailToMessage` returns "" for that shape (it has neither
 * `message` nor `blockedClaims`), so the generic `message` alone can't
 * distinguish "the agent is busy" from "you already have a session open
 * at <url>". */
export class BrowserSessionError extends Error {
  status: number;
  reason: BrowserSessionRefusalReason | null;
  conflictUrl: string | null;

  constructor(
    status: number,
    message: string,
    reason: BrowserSessionRefusalReason | null = null,
    conflictUrl: string | null = null,
  ) {
    super(message);
    this.name = "BrowserSessionError";
    this.status = status;
    this.reason = reason;
    this.conflictUrl = conflictUrl;
  }
}

/** Open an attended sign-in session at a URL.
 *
 * Deliberately does not go through `request`: this is the one call whose
 * status code the caller must branch on (409 = a run is in progress). */
export async function openBrowserSession(url: string): Promise<BrowserSession> {
  let res: Response;
  try {
    res = await fetch("/api/browser/session", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ url }),
    });
  } catch {
    throw new BrowserSessionError(0, "Can't reach the server. Check that TruthCV is running, then try again.");
  }
  if (!res.ok) {
    const body = await res.json().catch(() => null);
    const detail = errorDetailToMessage(body);
    const rawDetail =
      body && typeof body === "object" ? (body as { detail?: unknown }).detail : undefined;
    const reason =
      rawDetail && typeof rawDetail === "object" && typeof (rawDetail as { reason?: unknown }).reason === "string"
        ? ((rawDetail as { reason: string }).reason as BrowserSessionRefusalReason)
        : null;
    const conflictUrl =
      rawDetail && typeof rawDetail === "object" && typeof (rawDetail as { url?: unknown }).url === "string"
        ? ((rawDetail as { url: string }).url)
        : null;
    throw new BrowserSessionError(
      res.status,
      detail || `That didn't work (error ${res.status}).`,
      reason,
      conflictUrl,
    );
  }
  return (await res.json()) as BrowserSession;
}

/** Every prompt fragment in the library. */
export function listPromptFragments(): Promise<PromptFragment[]> {
  return request("/api/prompt-fragments");
}

/** Create or update a prompt fragment — PUT when it already has an id, POST
 * (server assigns the id) otherwise. */
export function savePromptFragment(fragment: Omit<PromptFragment, "seeded">): Promise<PromptFragment> {
  return request("/api/prompt-fragments" + (fragment.id ? `/${fragment.id}` : ""), {
    method: fragment.id ? "PUT" : "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(fragment),
  });
}

/** Delete a prompt fragment from the library. */
export function deletePromptFragment(id: string): Promise<void> {
  return request(`/api/prompt-fragments/${id}`, { method: "DELETE" });
}

/** Every prompt preset in the library. */
export function listPromptPresets(): Promise<PromptPreset[]> {
  return request("/api/prompt-presets");
}

/** Create or update a prompt preset — PUT when it already has an id, POST
 * (server assigns the id) otherwise. */
export function savePromptPreset(preset: Omit<PromptPreset, "seeded">): Promise<PromptPreset> {
  return request("/api/prompt-presets" + (preset.id ? `/${preset.id}` : ""), {
    method: preset.id ? "PUT" : "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(preset),
  });
}

/** Delete a prompt preset from the library. */
export function deletePromptPreset(id: string): Promise<void> {
  return request(`/api/prompt-presets/${id}`, { method: "DELETE" });
}

/** Check a candidate set of fragment ids for slot/declared conflicts before
 * saving a preset. */
export function validatePromptPreset(fragmentIds: string[]): Promise<PromptConflict[]> {
  return request<{ conflicts: PromptConflict[] }>("/api/prompt-presets/validate", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ fragmentIds }),
  }).then((result) => result.conflicts);
}

/** Mark a preset as the default used when no presetId is passed to generation. */
export function setDefaultPromptPreset(id: string): Promise<PromptPreset> {
  return request(`/api/prompt-presets/${id}/default`, { method: "PUT" });
}
