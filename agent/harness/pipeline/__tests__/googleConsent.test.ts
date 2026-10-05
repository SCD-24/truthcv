import { describe, expect, it } from 'vitest';
import { tryPassGoogleConsent } from '../googleConsent.js';
import type { BrowserToolCall } from '../../builtins/harvestTypes.js';

const CONSENT = 'https://consent.google.com/m?continue=x';
const BUTTON = `- Page URL: ${CONSENT}\n- button "Alle akzeptieren" [ref=e7]`;

function stub(snapshot: string, clickError = false): { call: BrowserToolCall; calls: [string, Record<string, unknown>][] } {
  const calls: [string, Record<string, unknown>][] = [];
  const call: BrowserToolCall = async (name, args) => {
    calls.push([name, args]);
    if (name === 'browser_snapshot') return { content: snapshot, isError: false };
    if (name === 'browser_click') return { content: 'x', isError: clickError };
    return { content: 'ok', isError: false };
  };
  return { call, calls };
}

describe('tryPassGoogleConsent', () => {
  it('clicks the accept button and waits', async () => {
    const { call, calls } = stub(BUTTON);
    expect(await tryPassGoogleConsent(call, CONSENT)).toBe(true);
    expect(calls.map((c) => c[0])).toEqual(['browser_navigate', 'browser_snapshot', 'browser_click', 'browser_wait_for']);
    expect(calls[2][1]).toEqual({ element: 'Alle akzeptieren', ref: 'e7' });
  });
  it('returns false when no accept button exists', async () => {
    expect(await tryPassGoogleConsent(stub('- button "Mehr" [ref=e1]').call, CONSENT)).toBe(false);
  });
  it('returns false when the click errors', async () => {
    expect(await tryPassGoogleConsent(stub(BUTTON, true).call, CONSENT)).toBe(false);
  });
  it('never acts on the /sorry CAPTCHA', async () => {
    const { call, calls } = stub(BUTTON);
    expect(await tryPassGoogleConsent(call, 'https://www.google.com/sorry/index')).toBe(false);
    expect(calls).toHaveLength(0);
  });
  it('returns false when a call throws', async () => {
    const call: BrowserToolCall = async () => { throw new Error('x'); };
    expect(await tryPassGoogleConsent(call, CONSENT)).toBe(false);
  });
});
