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

/**
 * Converts a parsed error response body into a display string.
 *
 * - A string `detail` (the common FastAPI HTTPException shape) passes through.
 * - An array `detail` (FastAPI's RequestValidationError shape) is mapped to
 *   "field: message" entries and joined with "; ".
 * - Anything else (missing detail, unparseable body, empty array) yields "".
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
  return "";
}
