import { describe, expect, it, vi } from 'vitest';
import { discover } from '../discover.js';
import { fetchPosting } from '../fetchPosting.js';
import { classifySnapshot } from '../../builtins/harvestClassify.js';
import { resolveLinks } from '../../builtins/harvestLinks.js';
import type { BrowserToolCall } from '../../builtins/harvestTypes.js';

const GOOD = '- Page URL: https://x.test\n' + [1, 2].map((n) => `- link "Job ${n}" [ref=e${n}]: https://boards.greenhouse.io/acme/jobs/${n}`).join('\n');
const okMcp = () => vi.fn(async (_t: string, _a: Record<string, unknown>) => ({ content: '{"recorded":true}', isError: false }));
const sleep = async () => {};

describe('discover record_postings_seen and keywords', () => {
  it('records unique candidate count once', async () => {
    const mcp = okMcp();
    const call: BrowserToolCall = async (t) => ({ content: t === 'browser_snapshot' ? GOOD : 'ok', isError: false });
    await discover({ searchQueries: [{ profiles: ['A'], url: 'https://www.google.com/search?q=a' }, { profiles: ['B'], url: 'https://www.google.com/search?q=b' }] }, 'r1', call, mcp, { sleep });
    const seen = mcp.mock.calls.filter((c) => c[0] === 'record_postings_seen');
    expect(seen).toHaveLength(1);
    expect(seen[0][1]).toEqual({ run_id: 'r1', count: 2 });
  });
  it('uses the first title keyword, falling back to keywords', async () => {
    const typed: string[] = [];
    const call: BrowserToolCall = async (t, a) => {
      if (t === 'browser_type') typed.push(String(a.text));
      return { content: t === 'browser_snapshot' ? '- searchbox "Search" [ref=e1]' : 'ok', isError: false };
    };
    const cfg = (p: Record<string, unknown>) => ({ directBoards: [{ url: 'https://b.test', profiles: [p] }] });
    await discover(cfg({ profile: 'A', title_keywords: ['Data Engineer', 'x'], keywords: ['k'] }), 'r', call, okMcp(), { sleep });
    await discover(cfg({ profile: 'A', keywords: ['k1', 'k2'] }), 'r', call, okMcp(), { sleep });
    expect(typed[0]).toBe('Data Engineer');
    expect(typed).toContain('k1 k2');
  });
});

describe('discover Google consent pass', () => {
  const CONSENT = '- Page URL: https://consent.google.com/m\n- button "Accept all" [ref=e3]\nbefore you continue to google';
  function consentBrowser(hasButton: boolean) {
    let accepted = false;
    const nav: string[] = [];
    const clicks: number[] = [];
    const call: BrowserToolCall = async (t, a) => {
      if (t === 'browser_navigate') nav.push(String(a.url));
      if (t === 'browser_click') { accepted = true; clicks.push(1); }
      if (t === 'browser_snapshot') {
        const last = nav[nav.length - 1] ?? '';
        const consent = hasButton ? CONSENT : CONSENT.replace('button "Accept all"', 'text: nope');
        return { content: last.includes('google.com/search') && accepted ? GOOD : consent, isError: false };
      }
      return { content: 'ok', isError: false };
    };
    return { call, clicks };
  }
  const dork = (n: number) => ({ searchQueries: Array.from({ length: n }, (_, i) => ({ profiles: ['A'], url: `https://www.google.com/search?q=${i}` })) });

  it('retries the dork after a successful consent pass', async () => {
    const { call, clicks } = consentBrowser(true);
    const mcp = okMcp();
    await discover(dork(1), 'r', call, mcp, { sleep });
    expect(clicks).toHaveLength(1);
    const cov = mcp.mock.calls.filter((c) => c[0] === 'record_discovery_coverage')[0][1];
    expect(cov.status).toBe('searched');
  });
  it('behaves as before when the button is absent, and tries at most once', async () => {
    const { call, clicks } = consentBrowser(false);
    const mcp = okMcp();
    await discover(dork(3), 'r', call, mcp, { sleep });
    expect(clicks).toHaveLength(0);
    const cov = mcp.mock.calls.filter((c) => c[0] === 'record_discovery_coverage').map((c) => c[1]);
    expect(cov[0].status).toBe('blocked');
    expect(cov[2].status).toBe('skipped');
    expect(String(cov[2].reason)).toContain('consent page could not be passed');
  });
  it('never clicks on the /sorry CAPTCHA', async () => {
    const clicks: string[] = [];
    const call: BrowserToolCall = async (t) => {
      if (t === 'browser_click') clicks.push(t);
      return { content: t === 'browser_snapshot' ? '- Page URL: https://www.google.com/sorry/index\nunusual traffic - button "Accept all" [ref=e1]' : 'ok', isError: false };
    };
    await discover(dork(2), 'r', call, okMcp(), { sleep });
    expect(clicks).toHaveLength(0);
  });
});

describe('fetchPosting onward link', () => {
  const LAND = '- Page URL: https://www.adzuna.de/land/ad/1\n- link "Weitere Informationen ❯" [ref=e1]:\n  - /url: /details/99\n- link "Apply" [ref=e2]:\n  - /url: /apply/1';
  const EMPLOYER = '- paragraph: ' + 'Employer posting text about the role. '.repeat(10);
  it('follows the onward link once and returns employer text', async () => {
    const nav: string[] = [];
    const call: BrowserToolCall = async (t, a) => {
      if (t === 'browser_navigate') nav.push(String(a.url));
      if (t === 'browser_snapshot') return { content: nav.length > 1 ? EMPLOYER : LAND, isError: false };
      return { content: 'ok', isError: false };
    };
    const r = await fetchPosting(call, 'https://www.adzuna.de/land/ad/1');
    expect((r as { text: string }).text).toContain('Employer posting text');
    expect(nav).toEqual(['https://www.adzuna.de/land/ad/1', 'https://www.adzuna.de/details/99']);
  });
  it('stays unreadable without an onward link', async () => {
    const call: BrowserToolCall = async (t) => ({ content: t === 'browser_snapshot' ? '- paragraph: hi' : 'ok', isError: false });
    expect(await fetchPosting(call, 'https://x.test/j')).toMatchObject({ unreadable: true, blocker: 'unreadable', reason: expect.stringContaining('onward link not found') });
  });
  it('navigates at most once more when the target is also thin', async () => {
    const nav: string[] = [];
    const call: BrowserToolCall = async (t, a) => {
      if (t === 'browser_navigate') nav.push(String(a.url));
      return { content: t === 'browser_snapshot' ? LAND : 'ok', isError: false };
    };
    const r = await fetchPosting(call, 'https://www.adzuna.de/land/ad/1');
    expect(r).toMatchObject({ unreadable: true });
    expect(nav).toHaveLength(2);
  });
});

describe('harvest link titles and diagnostics', () => {
  it('uses the title query param for a generic link title', () => {
    const snap = '- link "Weitere Informationen ❯" [ref=e1]:\n  - /url: https://a.test/x?title=Software_Engineer_%E2%80%93_Generative_AI';
    expect(resolveLinks({ board: 'b', url: 'https://a.test' }, snap)[0].title).toBe('Software Engineer – Generative AI');
  });
  it('adds compact diagnostics to the needs_review note', () => {
    const snap = '- Page URL: https://a.test/\n- link "About us here" [ref=e1]:\n  - /url: /about\n' + 'x'.repeat(250);
    const r = classifySnapshot({ board: 'b', url: 'https://a.test/', postingUrlPattern: 'https://a.test/job/*' }, snap);
    expect(r.outcome).toBe('needs_review');
    expect(r.note).toContain('no recognised posting URLs found; raw snapshot attached for manual review');
    expect(r.note).toContain('links seen: 1');
    expect(r.note).toContain('/about');
    expect(r.note.length).toBeLessThanOrEqual(300);
  });
});
