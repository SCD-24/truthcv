import { describe, expect, it } from 'vitest';
import { backoffDelay, retryDelayMs } from '../retry.js';

describe('retryDelayMs', () => {
  it('prefers Retry-After, clamped to the cap', () => {
    expect(retryDelayMs(0, 2_000, 60_000)).toBe(2_000);
    expect(retryDelayMs(0, 90_000, 60_000)).toBe(60_000);
  });

  it('falls back to capped backoff without Retry-After', () => {
    const d = retryDelayMs(1, undefined, 60_000);
    expect(d).toBeGreaterThanOrEqual(2_000);
    expect(d).toBeLessThan(3_000);
    expect(retryDelayMs(20, undefined, 5_000)).toBe(5_000);
  });
});

describe('backoffDelay', () => {
  it('is capped', () => {
    expect(backoffDelay(20, 5_000)).toBe(5_000);
  });
});
