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
  ProfileAnswers,
  ProfileAnswersUpdate,
  CoverLetterResult,
  CoverLetterApprovals,
  Application,
  ApplicationCreate,
  ApplicationUpdate,
  SaveDocumentResult,
  ScreeningRecord,
  CoverLetterDraft,
  CooldownStatus,
  AgentConfig,
  AgentConfigUpdate,
  AgentStatus,
  AgentRunResult,
  ConnectionStatus,
  ConnectionList,
  StartLoginResult,
  Routing,
  RoutingUpdate,
} from "./types";
import { errorDetailToMessage } from "./errorDetail";

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
    const detail = await res
      .json()
      .then((b) => errorDetailToMessage(b))
      .catch(() => "");
    throw new Error(detail || `That didn't work (error ${res.status}). Try again.`);
  }
  // Some routes (render download links) still return JSON; callers that expect
  // no body pass T = void and ignore the result.
  return res.status === 204 ? (undefined as T) : ((await res.json()) as T);
}

/** Step 1 — upload the LinkedIn PDF for text extraction. */
export async function uploadPdf(file: File): Promise<void> {
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
): Promise<CoverLetterResult> {
  return request("/api/cover-letter", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ tone, length, approvals, applicationId }),
  });
}

/** Every tracked job application, most recent first. */
export function listApplications(): Promise<Application[]> {
  return request("/api/applications");
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

/** Postings the agent rejected on a criterion — never queued, and reviewable
 * so a filter you disagree with does not silently lose a role. Filtered
 * client-side: an agent-criteria rejection has an empty `approval`, but so
 * does any other untouched record (`approval: str = ""` is the schema
 * default), so `?approval=` would also return records that were never
 * screened as rejected at all. */
export async function listDidNotPass(): Promise<ScreeningRecord[]> {
  const all = await listScreenings();
  return all.filter((s) => s.verdict === "rejected" && !s.approval);
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

/** Supply the URL a historical import left blank; the agent cannot apply
 * without one. */
export function setScreeningUrl(id: string, url: string): Promise<ScreeningRecord> {
  return request("/api/screenings/" + encodeURIComponent(id), {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ url }),
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
 * yours; without it the server refuses to overwrite your own words. */
export function generateScreeningLetter(id: string, force = false): Promise<CoverLetterDraft> {
  return request("/api/screenings/" + encodeURIComponent(id) + "/letter", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ force }),
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

/** Poll the agent supervisor for running/idle status. */
export function getAgentStatus(): Promise<AgentStatus> {
  return request("/api/agent/status");
}

/** List all provider connections and their status. */
export function listConnections(): Promise<ConnectionList> {
  return request("/api/auth/status");
}

/** Start a login flow for a provider. */
export function startLogin(provider: string): Promise<StartLoginResult> {
  return request(`/api/auth/${provider}/start`, { method: "POST" });
}

/** Complete a Claude login flow with an authorization code. */
export function completeClaudeLogin(code: string): Promise<ConnectionStatus> {
  return request("/api/auth/claude/complete", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ code }),
  });
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
