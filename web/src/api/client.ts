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
  CoverLetterResult,
  Application,
  ApplicationCreate,
  ApplicationUpdate,
  SaveDocumentResult,
} from "./types";

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
      .then((b) => (b && typeof b.detail === "string" ? b.detail : ""))
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

/** Generate a guardrail-truthful cover letter for the current posting. */
export function generateCoverLetter(
  tone: string,
  length: string,
  applicationId?: string,
): Promise<CoverLetterResult> {
  return request("/api/cover-letter", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ tone, length, applicationId }),
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
