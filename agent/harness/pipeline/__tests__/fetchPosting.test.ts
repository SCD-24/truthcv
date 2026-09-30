import { describe, expect, it } from 'vitest';
import { fetchPosting, postingBodyText } from '../fetchPosting.js';
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
  it('survives a snapshot error during the wait', async () => {
    const { call, names } = stub([ok(SHELL), { content: BODY, isError: true }]);
    const r = await fetchPosting(call, 'https://x.test/j');
    expect(r).toMatchObject({ unreadable: true, blocker: 'unreadable' });
    expect(waits(names)).toBe(1);
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
