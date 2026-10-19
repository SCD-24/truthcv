/**
 * Shared provider retry helpers: exponential backoff with jitter, and the
 * delay policy used by pipeline stages that call a provider adapter directly.
 */

/** Base unit for exponential backoff and its jitter, in milliseconds. */
const BASE_RETRY_DELAY_MS = 1_000;

/** Longest a pipeline stage waits between provider retries, in milliseconds. */
export const PIPELINE_MAX_RETRY_DELAY_MS = 60_000;

/** Provider attempts per call when the failure is retryable (rate limit etc.). */
export const PROVIDER_RETRY_ATTEMPTS = 4;

/** Injectable sleep, so tests never wait on a real timer. */
export type Sleep = (ms: number) => Promise<void>;

/** Real sleep backed by `setTimeout`. */
export const realSleep: Sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));

/**
 * Exponential backoff with jitter, capped at `maxRetryDelayMs`.
 *
 * The cap matters: a provider effectively saying "retry in four hours" must
 * fail fast against the cap instead of parking the run for hours.
 */
export function backoffDelay(attempt: number, maxRetryDelayMs: number): number {
  const base = BASE_RETRY_DELAY_MS * 2 ** attempt;
  const jitter = Math.random() * BASE_RETRY_DELAY_MS;
  return Math.min(base + jitter, maxRetryDelayMs);
}

/**
 * Delay before the next retry: the provider's `Retry-After` when it sent one
 * (clamped to `capMs`), else the computed backoff for `attempt`.
 *
 * @param attempt Zero-based count of retries already made.
 * @param retryAfterMs The provider's requested wait, if any.
 * @param capMs Upper bound on the returned delay.
 */
export function retryDelayMs(attempt: number, retryAfterMs: number | undefined, capMs: number): number {
  return retryAfterMs === undefined ? backoffDelay(attempt, capMs) : Math.min(retryAfterMs, capMs);
}
