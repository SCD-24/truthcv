import { describe, it, expect, vi } from 'vitest';
import { discover } from '../discover.js';
import { companyFromUrl, roleForBlocker, BLOCKER_ROLE_FALLBACK, BLOCKER_COMPANY_FALLBACK } from '../blockerIdentity.js';
import { buildToolRegistry, executeToolCall, sessionDeniedTools } from '../../tools.js';
import type { McpClientPool } from '../../mcp/client.js';
import type { BrowserToolCall } from '../../builtins/harvestTypes.js';

describe('roleForBlocker', () => {
  it.each(['Apply now', 'apply', ' - View Job - ', 'Full-Time', 'N/A', '12345', 'https://x.test/j', 'www.x.test'])('rejects %s', (t) => {
    expect(roleForBlocker(t)).toBe(BLOCKER_ROLE_FALLBACK);
  });
  it('keeps a real title, normalized', () => {
    expect(roleForBlocker('  Senior   Engineer | ')).toBe('Senior Engineer');
  });
});

describe('companyFromUrl', () => {
  it.each([
    ['https://boards.greenhouse.io/acme/jobs/1', 'acme'],
    ['https://jobs.lever.co/big-corp/abc', 'big corp'],
    ['https://jobs.ashbyhq.com/foo/123', 'foo'],
    ['https://apply.workable.com/bar/j/1', 'bar'],
    ['https://acme.recruitee.com/o/x', 'acme'],
    ['https://acme.jobs.personio.de/job/1', 'acme'],
    ['https://acme.wd3.myworkdayjobs.com/en/x', 'acme'],
    ['https://www.example.com/jobs/1', 'example.com'],
    ['https://careers.example.com/1', 'example.com'],
  ])('%s -> %s', (url, want) => {
    expect(companyFromUrl(url)).toBe(want);
  });
  it('falls back on an unparsable URL', () => {
    expect(companyFromUrl('nope')).toBe(BLOCKER_COMPANY_FALLBACK);
  });
});

function recorder(): { call: BrowserToolCall; navs: string[] } {
  const navs: string[] = [];
  const call: BrowserToolCall = async (tool, args) => {
    if (tool === 'browser_navigate') navs.push(String(args.url));
    return { content: tool === 'browser_snapshot' ? '- Page URL: https://b.test\nNo matching jobs found' : 'ok', isError: false };
  };
  return { call, navs };
}

const okMcp = () => vi.fn(async (_t: string, _a: Record<string, unknown>) => ({ content: '{"recorded":true}', isError: false }));
const covCalls = (m: ReturnType<typeof okMcp>) => m.mock.calls.filter((c) => c[0] === 'record_discovery_coverage').map((c) => c[1]);

describe('discover round 2', () => {
  it('harvests every location but records one aggregated coverage per board', async () => {
    const mcp = okMcp();
    const { call, navs } = recorder();
    await discover({ directBoards: [{ url: 'https://b.test/jobs', profiles: [{ profile: 'A', locations: ['Berlin', 'Paris'] }] }] }, 'r', call, mcp);
    expect(navs.filter((u) => u === 'https://b.test/jobs').length).toBeGreaterThanOrEqual(2);
    expect(covCalls(mcp).filter((c) => c.channel === 'direct')).toHaveLength(1);
  });

  it('records a partial feed failure without dropping postings', async () => {
    const mcp = okMcp();
    const out = await discover({ feedError: 'source X down', feedPostings: [{ url: 'https://f.test/1', title: 'T', source: 'rr', profile: 'A' }] }, 'r', recorder().call, mcp);
    expect(out.coverageComplete).toBe(false);
    expect(out.errors.join()).toContain('source X down');
    expect(out.candidates.map((c) => c.url)).toContain('https://f.test/1');
    const feed = covCalls(mcp).filter((c) => c.channel === 'feed');
    expect(feed.map((c) => c.status).sort()).toEqual(['extraction_failed', 'searched']);
  });
});

describe('apply-session tool deny set', () => {
  const tools = ['start_run', 'finish_run', 'finish_phase', 'finish_application', 'record_application'].map((t) => ({
    namespacedName: `truthcv__${t}`, serverName: 'truthcv', toolName: t, description: '', inputSchema: {},
  })) as unknown as ReturnType<McpClientPool['listTools']>;
  const names = (r: ReturnType<typeof buildToolRegistry>) => r.map((t) => t.toolName);

  it('excludes lifecycle tools for finish_application and refuses a direct call', async () => {
    const denied = sessionDeniedTools('finish_application');
    const reg = buildToolRegistry(tools, denied);
    expect(names(reg)).not.toContain('start_run');
    expect(names(reg)).not.toContain('finish_run');
    expect(names(reg)).not.toContain('finish_phase');
    expect(names(reg)).toContain('finish_application');
    const pool = { callTool: vi.fn() } as unknown as McpClientPool;
    const full = buildToolRegistry(tools);
    const res = await executeToolCall(pool, { id: '1', name: 'truthcv__finish_run', arguments: {} }, full, undefined, undefined, undefined, denied);
    expect(res.isError).toBe(true);
    expect((pool.callTool as ReturnType<typeof vi.fn>)).not.toHaveBeenCalled();
  });

  it('changes nothing for finish_run', () => {
    expect(sessionDeniedTools('finish_run')).toEqual([]);
    expect(names(buildToolRegistry(tools, sessionDeniedTools('finish_run')))).toContain('start_run');
  });
});
