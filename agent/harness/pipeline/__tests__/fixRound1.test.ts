import { describe, expect, it, vi } from 'vitest';
import { findOnwardUrl } from '../followOnward.js';
import { tryPassGoogleConsent } from '../googleConsent.js';
import { discover } from '../discover.js';
import { resolveLinks } from '../../builtins/harvestLinks.js';
import type { BrowserToolCall } from '../../builtins/harvestTypes.js';

describe('findOnwardUrl apply guard', () => {
  it('does not follow /applications/start', () => {
    const snap = '- Page URL: https://ats.example/job/1\n- link "View job" [ref=e1]: https://ats.example/applications/start';
    expect(findOnwardUrl(snap, 'https://ats.example/job/1')).toBeUndefined();
  });
  it('does not mistake /authority/ for an auth path', () => {
    const snap = '- Page URL: https://ats.example/job/1\n- link "View job" [ref=e1]: https://ats.example/authority/jobs/42';
    expect(findOnwardUrl(snap, 'https://ats.example/job/1')).toBe('https://ats.example/authority/jobs/42');
  });
  it('still follows a normal onward link', () => {
    const snap = '- Page URL: https://ats.example/job/1\n- link "View job" [ref=e1]: https://ats.example/jobs/42';
    expect(findOnwardUrl(snap, 'https://ats.example/job/1')).toBe('https://ats.example/jobs/42');
  });
});

describe('tryPassGoogleConsent redirect', () => {
  it('does not click when redirected to /sorry', async () => {
    const calls: string[] = [];
    const call: BrowserToolCall = async (name) => {
      calls.push(name);
      if (name === 'browser_snapshot') return { content: '- Page URL: https://www.google.com/sorry/index\n- button "Accept all" [ref=e1]', isError: false };
      return { content: 'ok', isError: false };
    };
    expect(await tryPassGoogleConsent(call, 'https://consent.google.com/m?continue=x')).toBe(false);
    expect(calls).not.toContain('browser_click');
  });
});

describe('tryPassGoogleConsent unknown page URL', () => {
  it('fails closed when the snapshot has no Page URL line', async () => {
    const calls: string[] = [];
    const call: BrowserToolCall = async (name) => {
      calls.push(name);
      if (name === 'browser_snapshot') return { content: '- button "Accept all" [ref=e1]', isError: false };
      return { content: 'ok', isError: false };
    };
    expect(await tryPassGoogleConsent(call, 'https://consent.google.com/m?continue=x')).toBe(false);
    expect(calls).not.toContain('browser_click');
  });
});

describe('discover record_postings_seen recorded:false', () => {
  it('is treated as a failure', async () => {
    const mcp = vi.fn(async (tool: string, _a: Record<string, unknown>) => ({
      content: tool === 'record_postings_seen' ? '{"recorded":false}' : '{"recorded":true}',
      isError: false,
    }));
    const cfg = { feedPostings: [{ url: 'https://feed.test/1', title: 'Feed job', source: 'rr', profile: 'A' }] };
    const out = await discover(cfg, 'r', async () => ({ content: 'ok', isError: false }), mcp, { sleep: async () => {} });
    expect(out.coverageComplete).toBe(false);
  });
});

describe('resolveLinks generic labels', () => {
  it('uses the URL title for an "Apply now" link', () => {
    const snap = '- Page URL: https://x.test/\n- link "Apply now" [ref=e1]: https://x.test/j/1?title=Data_Engineer';
    const links = resolveLinks({ url: 'https://x.test/' } as never, snap);
    expect(links[0].title).toBe('Data Engineer');
  });
});
