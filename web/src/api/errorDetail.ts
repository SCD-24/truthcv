/**
 * Turns a parsed error response body into a human-readable message.
 *
 * FastAPI's RequestValidationError returns `detail` as an array of
 * {loc, msg, type} objects rather than a plain string, so callers can't
 * just read `body.detail` and show it — this module normalizes both shapes.
 */

/** A single FastAPI validation error entry. */
interface ValidationErrorItem {
  loc?: unknown;
  msg?: unknown;
  type?: unknown;
}

/**
 * Picks the most specific location segment for an error entry: the last
 * segment of `loc` that isn't the literal "body" (which just indicates the
 * request body was the source, not a useful field name).
 */
function lastMeaningfulSegment(loc: unknown): string {
  if (!Array.isArray(loc)) return "";
  const segments = loc.filter((seg) => seg !== "body");
  const last = segments[segments.length - 1];
  return last === undefined || last === null ? "" : String(last);
}

/**
 * Formats one validation error entry as "segment: msg", or just "msg" if
 * there's no usable location segment.
 */
function formatValidationItem(item: ValidationErrorItem): string {
  const segment = lastMeaningfulSegment(item.loc);
  const msg = typeof item.msg === "string" ? item.msg : "";
  return segment ? `${segment}: ${msg}` : msg;
}

/** A blocked-claim entry as the letter routes send it (guardrail/validate.py
 * BlockedClaim, asdict'd — snake_case keys except `text`, which is spelled
 * the same either way, so it's the only field read here). */
interface BlockedClaimItem {
  text?: unknown;
}

/**
 * Converts a parsed error response body into a display string.
 *
 * - A string `detail` (the common FastAPI HTTPException shape) passes through.
 * - An array `detail` (FastAPI's RequestValidationError shape) is mapped to
 *   "field: message" entries and joined with "; ".
 * - An object `detail` (e.g. the letter routes' guardrail-block shape:
 *   {message, blockedReason, blockedClaims}) renders `message`, plus each
 *   blocked claim's `text` appended so the operator sees exactly what
 *   tripped the guardrail rather than a generic failure.
 * - Anything else (missing detail, unparseable body, empty array, an object
 *   with neither field) yields "".
 */
export function errorDetailToMessage(body: unknown): string {
  if (!body || typeof body !== "object") return "";
  const detail = (body as { detail?: unknown }).detail;
  if (typeof detail === "string") return detail;
  if (Array.isArray(detail)) {
    return detail
      .filter((item): item is ValidationErrorItem => !!item && typeof item === "object")
      .map(formatValidationItem)
      .join("; ");
  }
  if (detail && typeof detail === "object") {
    const obj = detail as { message?: unknown; blockedClaims?: unknown };
    const message = typeof obj.message === "string" ? obj.message : "";
    const claims = Array.isArray(obj.blockedClaims) ? obj.blockedClaims : [];
    const claimTexts = claims
      .filter((c): c is BlockedClaimItem => !!c && typeof c === "object")
      .map((c) => (typeof c.text === "string" ? c.text : ""))
      .filter((text) => text !== "");
    if (!message && claimTexts.length === 0) return "";
    return claimTexts.length ? `${message} Blocked: ${claimTexts.join("; ")}` : message;
  }
  return "";
}
