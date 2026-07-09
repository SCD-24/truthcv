import type {
  TruthEntry,
  TailorResult,
  RenderResult,
  SettingsStatus,
  SettingsUpdate,
  TestResult,
  ProfileStatus,
  CoverLetterResult,
} from "./types";

/**
 * Typed wrappers over the wizard's REST routes. Served same-origin by the API
 * (dev proxies /api to the backend), so the base is empty. Every wrapper throws
 * an Error with an actionable, user-facing message when the request fails — the
 * step components surface that message directly.
 */

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  let res: Response;
  try {
    res = await fetch(path, init);
  } catch {
    throw new Error(
      "Can't reach the server. Check that TruthCV is running, then try again.",
    );
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
export function extractTruth(): Promise<{ entries: TruthEntry[] }> {
  return request("/api/extract", { method: "POST" });
}

/** Step 2 — load the current truth file for review. */
export function getTruth(): Promise<{ entries: TruthEntry[] }> {
  return request("/api/truth");
}

/** Step 2 — persist the user's corrections. After this, the facts are trusted. */
export function saveTruth(entries: TruthEntry[]): Promise<void> {
  return request<void>("/api/truth", {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ entries }),
  });
}

/** Step 3 — best-effort fetch of a posting from a URL to pre-fill the box. */
export function fetchPosting(url: string): Promise<{ text: string }> {
  return request("/api/job/fetch", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ url }),
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

/** Step 4 — approve/reject inferences; approved become source:user-confirmed. */
export function confirmInferences(approvedIds: string[]): Promise<void> {
  return request<void>("/api/confirm-inferences", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ approvedIds }),
  });
}

/** Step 5 — run guardrail + ATS review and render PDF/DOCX. */
export function render(): Promise<RenderResult> {
  return request("/api/render", { method: "POST" });
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
): Promise<CoverLetterResult> {
  return request("/api/cover-letter", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ tone, length }),
  });
}
