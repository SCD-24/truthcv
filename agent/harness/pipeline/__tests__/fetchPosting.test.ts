import { describe, expect, it } from 'vitest';
import { fetchPosting, linkedInSignedOut, postingBodyText } from '../fetchPosting.js';
import type { BrowserToolCall } from '../../builtins/harvestTypes.js';

type Snap = { content: string; isError: boolean };
const ok = (content: string): Snap => ({ content, isError: false });

/** Navigate + snapshot sequence stub; records tool names. */
function stub(snapshots: Snap[]): { call: BrowserToolCall; names: string[] } {
  const names: string[] = [];
  let i = 0;
  const call: BrowserToolCall = async (name) => {
    names.push(name);
    if (name === 'browser_snapshot') return snapshots[Math.min(i++, snapshots.length - 1)];
    return ok('ok');
  };
  return { call, names };
}

const waits = (names: string[]) => names.filter((n) => n === 'browser_wait_for').length;

const SHELL =
  '### Page\n- Page URL: https://haystack.cv/jobs/3f2b8c1e-9d4a-4e7b-8a61-5c0d2f7e9b13\n' +
  '- Page Title: Haystack – Get hired without the hassle\n- Console: 3 errors, 0 warnings\n' +
  '### Snapshot\n```yaml\n- generic [ref=e2]:\n  - region "Notifications (F8)" [ref=e3]\n```';
const BODY =
  '- heading "Electrical Design Engineer" [ref=e5]\n' +
  '- paragraph [ref=e6]: ' + 'Design power distribution systems for industrial clients. '.repeat(5);

describe('fetchPosting thin-page wait', () => {
  it('shell is longer than the threshold raw', () => {
    expect(SHELL.length).toBeGreaterThan(200);
  });
  it('waits once for a shell that then fills', async () => {
    const { call, names } = stub([ok(SHELL), ok(BODY)]);
    const r = await fetchPosting(call, 'https://haystack.cv/jobs/x');
    expect(r.unreadable).toBeFalsy();
    expect(waits(names)).toBe(1);
  });
  it('gives up after four waits', async () => {
    const { call, names } = stub([ok(SHELL)]);
    const r = await fetchPosting(call, 'https://haystack.cv/jobs/x');
    expect(r).toMatchObject({ unreadable: true, blocker: 'unreadable' });
    expect(waits(names)).toBe(4);
  });
  it('does not wait for a readable page', async () => {
    const { call, names } = stub([ok(BODY)]);
    await fetchPosting(call, 'https://x.test/j');
    expect(waits(names)).toBe(0);
  });
  it('flags login walls without waiting', async () => {
    const { call, names } = stub([ok('Please sign in to view this job')]);
    const r = await fetchPosting(call, 'https://x.test/j');
    expect(r).toMatchObject({ unreadable: true, blocker: 'login_required' });
    expect(waits(names)).toBe(0);
  });
  it('snapshot error during the wait → failed', async () => {
    const { call, names } = stub([ok(SHELL), { content: BODY, isError: true }]);
    const r = await fetchPosting(call, 'https://x.test/j');
    expect(r).toMatchObject({ failed: true });
    expect((r as { reason: string }).reason).toContain(BODY);
    expect(waits(names)).toBe(1);
  });
  it('call throwing during the wait → failed', async () => {
    const call: BrowserToolCall = async (name) => {
      if (name === 'browser_wait_for') throw new Error('transport closed');
      return ok(SHELL);
    };
    expect(await fetchPosting(call, 'https://x.test/j')).toEqual({ failed: true, reason: 'transport closed' });
  });
});

describe('fetchPosting load failures', () => {
  const MCP = "MCP server 'browser' is not connected: MCP error -32001: Request timed out";
  it('navigate isError → failed, not unreadable', async () => {
    const call: BrowserToolCall = async () => ({ content: MCP, isError: true });
    const r = await fetchPosting(call, 'https://x.test/j');
    expect(r).toMatchObject({ failed: true });
    expect((r as { reason: string }).reason).toContain(MCP);
    expect(r.unreadable).toBeFalsy();
  });
  it('navigate throwing → failed', async () => {
    const call: BrowserToolCall = async () => { throw new Error('transport closed'); };
    expect(await fetchPosting(call, 'https://x.test/j')).toEqual({ failed: true, reason: 'transport closed' });
  });
  it('snapshot isError after navigate → failed', async () => {
    const call: BrowserToolCall = async (name) => (name === 'browser_snapshot' ? { content: 'boom', isError: true } : ok('ok'));
    expect(await fetchPosting(call, 'https://x.test/j')).toMatchObject({ failed: true });
  });
  it('thin page is still unreadable', async () => {
    const { call } = stub([ok('- paragraph: hi')]);
    expect(await fetchPosting(call, 'https://x.test/j')).toMatchObject({ unreadable: true, blocker: 'unreadable' });
  });
});

const LI_URL = 'https://www.linkedin.com/jobs/view/senior-architect-123';
const liChrome =
  '- Page Title: Architect | LinkedIn\n- banner [ref=e1]:\n' +
  '  - navigation "Primary" [ref=e2]:\n' +
  ['Home', 'My Network', 'Jobs', 'Messaging', 'Notifications'].map((n) => `    - link "${n}" [ref=e3]:\n      - /url: https://www.linkedin.com/${n}`).join('\n') +
  '\n- main [ref=e9]:\n  - region "Primary content" [ref=e10]\n';
const LI_DESC = 'Design enterprise data platforms for large clients. '.repeat(5);
const liFilled =
  liChrome.replace('region "Primary content" [ref=e10]', 'region "Primary content" [ref=e10]:\n    - paragraph [ref=e11]: ' + LI_DESC) +
  '- complementary "Aside" [ref=e12]:\n  - heading "Try Premium" [ref=e13]\n';

describe('fetchPosting LinkedIn readiness', () => {
  it('chrome-only snapshot waits four times and reports the LinkedIn reason', async () => {
    expect(liChrome.length).toBeGreaterThan(200);
    const { call, names } = stub([ok(liChrome)]);
    const r = await fetchPosting(call, LI_URL);
    expect(r).toEqual({ unreadable: true, blocker: 'unreadable', reason: 'LinkedIn job details did not load' });
    expect(waits(names)).toBe(4);
  });
  it('waits through the loading marker then returns pruned text', async () => {
    const loading = liChrome + '  - status "Loading the job description"\n';
    const { call } = stub([ok(loading), ok(liFilled)]);
    const r = await fetchPosting(call, LI_URL);
    expect(r.unreadable).toBeFalsy();
    const text = (r as { text: string }).text;
    expect(text).toContain('Design enterprise data platforms');
    expect(text).not.toContain('Premium');
    expect(text).not.toContain('[ref=');
    expect(text).not.toContain('/url:');
  });
});

describe('fetchPosting LinkedIn signed-out', () => {
  const wallSnap = '- Page URL: https://www.linkedin.com/authwall?trk=x\n' + liChrome;
  it('maps an authwall URL to a sign-in wall without waiting', async () => {
    const { call, names } = stub([ok(wallSnap)]);
    const r = await fetchPosting(call, LI_URL);
    expect(r).toEqual({ unreadable: true, blocker: 'login_required', reason: 'sign-in wall' });
    expect(waits(names)).toBe(0);
  });
  it('keeps the unready reason for a normal job URL', async () => {
    const { call, names } = stub([ok('- Page URL: https://www.linkedin.com/jobs/view/123\n' + liChrome)]);
    const r = await fetchPosting(call, LI_URL);
    expect(r).toMatchObject({ reason: 'LinkedIn job details did not load' });
    expect(waits(names)).toBe(4);
  });
  it('does not map a non-LinkedIn URL', async () => {
    const { call } = stub([ok(wallSnap)]);
    const r = await fetchPosting(call, 'https://x.test/j');
    expect(r).toMatchObject({ unreadable: true, blocker: 'unreadable' });
  });
});

describe('fetchPosting readability measure', () => {
  it('keeps waiting when the sign-in phrase is only in a dropped banner', async () => {
    const banner = '- banner [ref=e1]:\n  - text: Please sign in to view jobs\n- main [ref=e2]:\n  - paragraph [ref=e3]: short';
    const { call, names } = stub([ok(banner), ok(BODY)]);
    const r = await fetchPosting(call, 'https://x.test/j');
    expect(r.unreadable).toBeFalsy();
    expect((r as { text: string }).text).toContain('Electrical Design Engineer');
    expect(waits(names)).toBe(1);
  });
  it('measures length after whitespace collapse', async () => {
    const spaced = '- paragraph: ' + 'ab      '.repeat(30);
    const { call } = stub([ok(spaced)]);
    const r = await fetchPosting(call, 'https://x.test/j');
    expect(r).toMatchObject({ unreadable: true, blocker: 'unreadable' });
  });
});

describe('linkedInSignedOut', () => {
  it.each(['https://www.linkedin.com/authwall?trk=x', 'https://www.linkedin.com/login', 'https://ie.linkedin.com/uas/login?x=1', 'https://www.linkedin.com/checkpoint/lg/login'])('flags %s', (u) => {
    expect(linkedInSignedOut(`- Page URL: ${u}\n- main`)).toBe(true);
  });
  it.each(['https://www.linkedin.com/login-help', 'https://www.linkedin.com/jobs/view/123', 'https://www.linkedin.com/signups-closed'])('does not flag %s', (u) => {
    expect(linkedInSignedOut(`- Page URL: ${u}\n- main`)).toBe(false);
  });
});

describe('postingBodyText', () => {
  it('strips header, fences and ref tokens but keeps headings', () => {
    const out = postingBodyText(SHELL + '\n- heading "Electrical Design Engineer" [ref=e9]');
    expect(out).toBe('- generic : - region "Notifications (F8)" - heading "Electrical Design Engineer"');
    expect(out).not.toContain('ref=');
    expect(out).not.toContain('Page URL');
    expect(out).not.toContain('```');
  });
  it('keeps body lines that only start like a header marker', () => {
    expect(postingBodyText('### Page Designer\n  - text: ### Snapshot tools')).toBe('### Page Designer - text: ### Snapshot tools');
  });
});
