/**
 * Shared request-timeout handling for provider adapters.
 *
 * Each adapter's own fetch call had no timeout at all: a hung TCP connection
 * (no reset, no DNS failure — just silence) would wedge that turn forever
 * instead of surfacing as the same retryable network error a real connection
 * failure produces.
 */

/**
 * Default budget for a provider request, in milliseconds.
 *
 * For the non-streaming adapters (Anthropic Messages, OpenAI Chat
 * Completions) this signal covers the *entire* request — connect through
 * full body read, since `response.json()` runs under the same
 * `AbortSignal.timeout`. A slow local model (e.g. Ollama) that is healthy but
 * generating for minutes needs this to be a generous whole-request budget,
 * not just a connect timeout.
 */
export const PROVIDER_REQUEST_TIMEOUT_MS = 300_000;

/**
 * True when `err` is a timeout abort: the `TimeoutError` DOMException
 * `AbortSignal.timeout` raises, or an `AbortError` DOMException caused by our
 * own timeout signal firing. The latter shows up when a runtime reports a
 * signal-aborted body read as a generic abort rather than as `TimeoutError`;
 * `signal` (the signal we created for the request) lets us confirm it was
 * ours, rather than treating any unrelated abort as a timeout.
 */
export function isTimeoutError(err: unknown, signal?: AbortSignal): boolean {
  if (!(err instanceof DOMException)) return false;
  if (err.name === 'TimeoutError') return true;
  return err.name === 'AbortError' && signal?.aborted === true;
}

/**
 * Replace a timeout abort with a plain, readable cause; pass any other error
 * through unchanged. Intended for a catch block feeding `networkErrorEvent`,
 * so a hung connection reads as "request timed out" rather than the DOMException's
 * own generic "signal timed out" wording. Pass the signal that guards the
 * request so an `AbortError` caused by it is recognised too.
 */
export function describeTimeout(err: unknown, signal?: AbortSignal): unknown {
  return isTimeoutError(err, signal) ? new Error('the request timed out') : err;
}

/**
 * Inactivity budget for a streaming adapter's body read, in milliseconds.
 *
 * Unlike {@link PROVIDER_REQUEST_TIMEOUT_MS}, this does not bound the whole
 * stream — it resets on every chunk received, so a healthy multi-minute
 * stream that keeps producing tokens is never killed by it. Only a stream
 * that goes silent for this long is treated as dead.
 */
export const STREAM_INACTIVITY_TIMEOUT_MS = 60_000;
