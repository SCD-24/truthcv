/**
 * Shared construction of provider error events.
 *
 * Both adapters used to report a non-2xx as the HTTP status alone, which made
 * two different operator problems read identically: a 429 for a per-minute rate
 * limit and a 429 for an exhausted quota need opposite responses (wait vs. top
 * up the account), and the provider says which in the response body. Losing it
 * turned a one-line diagnosis into a hunt.
 */

import type { HarnessEvent } from './types.js';

/** Longest provider message kept. Enough for a real explanation, short enough
 * that an HTML error page cannot flood the run log. */
const MAX_DETAIL = 300;

/**
 * The response body as text, or '' when it cannot be read.
 *
 * A body that fails to read — a truncated connection, a stub without `text` —
 * must not turn a reportable provider error into a thrown exception the retry
 * loop never sees.
 */
export async function readBody(response: { text?: () => Promise<string> }): Promise<string> {
  try {
    return (await response.text?.()) ?? '';
  } catch {
    return '';
  }
}

/**
 * The provider's own explanation, pulled out of an error response body.
 *
 * Both vendors nest it at `error.message`; anything else (a plain string, an
 * HTML error page from a proxy in front of the API) falls back to the raw text
 * so the operator still sees something. Whitespace is collapsed to keep the
 * NDJSON run log one event per line.
 */
export function detailFromBody(body: string): string {
  const trimmed = body.trim();
  if (!trimmed) return '';
  let text = trimmed;
  try {
    const parsed = JSON.parse(trimmed) as { error?: { message?: unknown }; message?: unknown };
    const message = parsed?.error?.message ?? parsed?.message;
    if (typeof message === 'string' && message.trim()) text = message.trim();
  } catch {
    // Not JSON: keep the raw text.
  }
  const collapsed = text.replace(/\s+/g, ' ');
  return collapsed.length > MAX_DETAIL ? `${collapsed.slice(0, MAX_DETAIL)}…` : collapsed;
}

/**
 * Build an error HarnessEvent for a non-2xx response.
 *
 * `body` is the response text, read by the caller. A body that could not be
 * read is passed as '', and the event degrades to the status-only message it
 * always was.
 */
export function providerErrorEvent(
  vendor: string,
  status: number,
  body: string,
  retryable: boolean,
  retryAfterMs?: number,
): HarnessEvent {
  const detail = detailFromBody(body);
  const suffix = retryAfterMs === undefined ? '' : ` (retry-after ${Math.round(retryAfterMs / 1000)}s)`;
  return {
    type: 'error',
    message: `${vendor} request failed with status ${status}${detail ? `: ${detail}` : ''}${suffix}`,
    retryable,
    ...(retryAfterMs === undefined ? {} : { retryAfterMs }),
  };
}

/**
 * The `Retry-After` header as milliseconds, or undefined when absent or
 * unusable.
 *
 * RFC 9110 allows two forms and providers use both: delta-seconds, and an
 * HTTP-date. A date in the past yields 0 (retry now), never a negative delay.
 * Anything unparseable is dropped rather than guessed at — the loop's own
 * exponential backoff is the correct fallback.
 */
export function retryAfterMsFrom(headers: { get?: (name: string) => string | null } | undefined): number | undefined {
  const raw = headers?.get?.('retry-after');
  if (!raw) return undefined;
  const trimmed = raw.trim();
  if (/^\d+$/.test(trimmed)) return Number(trimmed) * 1000;
  const at = Date.parse(trimmed);
  if (Number.isNaN(at)) return undefined;
  return Math.max(0, at - Date.now());
}
