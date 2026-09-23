import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import type { McpClientPool, NamespacedTool } from '../mcp/client.js';
import type { HarnessEvent, ProviderAdapter, ToolCall } from '../providers/types.js';
import {
  buildToolRegistry,
  checkAdvertisedBrowserTools,
  DEFAULT_MAX_TOOL_RESULT_CHARS,
  executeToolCall,
  isToolAllowed,
  type RegisteredTool,
} from '../tools.js';
import type { BrowserToolResult } from '../builtins/harvestPostings.js';
import { McpClientPool as LiveMcpClientPool } from '../mcp/client.js';

/** A stub {@link ProviderAdapter} that yields exactly the given script once. */
function stubScreeningAdapter(script: HarnessEvent[]): ProviderAdapter {
  return {
    async *sendMessage() {
      for (const event of script) yield event;
    },
  };
}

/** A valid screen_posting call's arguments. */
const SCREEN_POSTING_ARGS = {
  url: 'https://example.com/jobs/1',
  role: 'Senior Engineer',
  company: 'Example Corp',
  postingText: 'Fully remote, English required.',
  profile: 'Backend (Remote)',
  criteria: 'remote_model: remote',
};

/** A `done` event carrying a valid, passing verdict as its text. */
function doneWithPassingVerdict(): HarnessEvent {
  const verdict = JSON.stringify({
    verdict: 'passed',
    screeningBlocker: '',
    failingCriterion: '',
    reason: 'ok',
    remoteArrangement: 'remote',
    languageRequirement: '',
  });
  return { type: 'done', stopReason: 'end', message: { role: 'assistant', content: verdict } };
}

/** The 14 browser tools enumerated in the browser allow-list. */
const BROWSER_TOOLS = [
  'browser_navigate',
  'browser_click',
  'browser_type',
  'browser_file_upload',
  'browser_snapshot',
  'browser_take_screenshot',
  'browser_wait_for',
  'browser_press_key',
  'browser_select_option',
  'browser_handle_dialog',
  'browser_tab_list',
  'browser_tab_new',
  'browser_tab_select',
  'browser_tab_close',
];

/** The 19 truthcv tools granted individually by daily-apply.sh. */
const TRUTHCV_TOOLS = [
  'generate_cover_letter',
  'record_application',
  'record_screening',
  'check_cooldown',
  'get_canonical_cv',
  'get_profile_answers',
  'record_company_board',
  'get_job_profiles',
  'recommend_salary',
  'get_approved_applications',
  'report_apply_failure',
  'record_company_finding',
  'get_company_findings',
  'start_run',
  'finish_run',
  'record_run_note',
  'record_postings_seen',
  'record_discovery_coverage',
  'check_gmail_responses',
];

/** Build a one-entry registry for a (server, tool) pair. */
function registryFor(serverName: string, toolName: string): RegisteredTool[] {
  const tools: NamespacedTool[] = [
    { namespacedName: `${serverName}__${toolName}`, serverName, toolName, description: 'd', inputSchema: { type: 'object' } },
  ];
  return buildToolRegistry(tools as ReturnType<McpClientPool['listTools']>);
}

/** A tool call referencing a namespaced tool name. */
function callFor(namespacedName: string): ToolCall {
  return { id: 'call-1', name: namespacedName, arguments: {} };
}

describe('isToolAllowed', () => {
  it('grants every one of the 19 named truthcv tools', () => {
    for (const name of TRUTHCV_TOOLS) {
      expect(isToolAllowed('truthcv', name)).toBe(true);
    }
  });

  it('denies an unlisted truthcv tool', () => {
    expect(isToolAllowed('truthcv', 'delete_everything')).toBe(false);
    expect(isToolAllowed('truthcv', 'some_unlisted_19th_tool')).toBe(false);
  });

  it('grants only the enumerated browser allow-list tools, not the whole server', () => {
    for (const name of BROWSER_TOOLS) {
      expect(isToolAllowed('browser', name)).toBe(true);
    }
    // Previously granted as part of the whole-server grant; now denied.
    expect(isToolAllowed('browser', 'browser_totally_new_tool')).toBe(false);
  });

  it('denies a tool from an unknown server even if the name is a truthcv tool', () => {
    expect(isToolAllowed('some_other_server', 'start_run')).toBe(false);
  });
});

describe('executeToolCall', () => {
  it('denies an ungranted truthcv tool without calling pool.callTool', async () => {
    const callTool = vi.fn(() => {
      throw new Error('pool.callTool must not be invoked for a denied tool');
    });
    const pool = { callTool } as unknown as McpClientPool;
    const registry = registryFor('truthcv', 'delete_everything');

    const result = await executeToolCall(pool, callFor('truthcv__delete_everything'), registry);

    expect(result.isError).toBe(true);
    expect(result.content).toContain('delete_everything');
    expect(callTool).not.toHaveBeenCalled();
  });

  it('denies an unknown (unregistered) tool without calling pool.callTool', async () => {
    const callTool = vi.fn(() => {
      throw new Error('pool.callTool must not be invoked for an unknown tool');
    });
    const pool = { callTool } as unknown as McpClientPool;

    const result = await executeToolCall(pool, callFor('truthcv__never_registered'), []);

    expect(result.isError).toBe(true);
    expect(result.content).toContain('never_registered');
    expect(callTool).not.toHaveBeenCalled();
  });

  it('calls pool.callTool for an allowed tool and maps its result', async () => {
    const callTool = vi.fn(async () => ({ content: 'the tool output', isError: false }));
    const pool = { callTool } as unknown as McpClientPool;
    const registry = registryFor('truthcv', 'start_run');

    const result = await executeToolCall(pool, callFor('truthcv__start_run'), registry);

    expect(callTool).toHaveBeenCalledWith('truthcv__start_run', {});
    expect(result.isError).toBe(false);
    expect(result.content).toBe('the tool output');
    expect(result.toolCallId).toBe('call-1');
  });

  it('dispatches an allowlisted browser tool and maps its result', async () => {
    const callTool = vi.fn(async () => ({ content: 'navigated', isError: false }));
    const pool = { callTool } as unknown as McpClientPool;
    const registry = registryFor('browser', 'browser_click');

    const result = await executeToolCall(pool, callFor('browser__browser_click'), registry);

    expect(callTool).toHaveBeenCalledWith('browser__browser_click', {});
    expect(result.content).toBe('navigated');
  });

  it('denies a non-allowlisted browser tool without calling pool.callTool', async () => {
    const callTool = vi.fn(() => {
      throw new Error('pool.callTool must not be invoked for a denied browser tool');
    });
    const pool = { callTool } as unknown as McpClientPool;
    // A registry can only be built from an allowed tool now, so register it
    // directly to prove the call-time isToolAllowed check still denies it.
    const registry: RegisteredTool[] = [
      {
        namespacedName: 'browser__browser_totally_new_tool',
        serverName: 'browser',
        toolName: 'browser_totally_new_tool',
        definition: { name: 'browser__browser_totally_new_tool', description: 'd', inputSchema: { type: 'object' } },
      },
    ];

    const result = await executeToolCall(pool, callFor('browser__browser_totally_new_tool'), registry);

    expect(result.isError).toBe(true);
    expect(result.content).toContain('browser_totally_new_tool');
    expect(callTool).not.toHaveBeenCalled();
  });
});

describe('executeToolCall content cap', () => {
  it('leaves content under the cap byte-identical (no marker appended)', async () => {
    const content = 'x'.repeat(100);
    const callTool = vi.fn(async () => ({ content, isError: false }));
    const pool = { callTool } as unknown as McpClientPool;
    const registry = registryFor('truthcv', 'start_run');

    const result = await executeToolCall(pool, callFor('truthcv__start_run'), registry);

    expect(result.content).toBe(content);
    expect(result.content.length).toBe(100);
  });

  it('caps content over the default cap and names the omitted count', async () => {
    const content = 'a'.repeat(30000);
    const callTool = vi.fn(async () => ({ content, isError: false }));
    const pool = { callTool } as unknown as McpClientPool;
    const registry = registryFor('truthcv', 'start_run');

    const result = await executeToolCall(pool, callFor('truthcv__start_run'), registry);

    // Starts with exactly the first DEFAULT_MAX_TOOL_RESULT_CHARS characters.
    expect(result.content.startsWith(content.slice(0, DEFAULT_MAX_TOOL_RESULT_CHARS))).toBe(true);
    expect(result.content.length).toBeGreaterThan(DEFAULT_MAX_TOOL_RESULT_CHARS);
    // The marker names the omitted count (30000 - 24000 = 6000) and tells the
    // model to re-request a narrower view.
    const omitted = 30000 - DEFAULT_MAX_TOOL_RESULT_CHARS;
    expect(result.content).toContain(String(omitted));
    expect(result.content).toContain('re-request');
  });

  it('also caps a long error body', async () => {
    const content = 'e'.repeat(30000);
    const callTool = vi.fn(async () => ({ content, isError: true }));
    const pool = { callTool } as unknown as McpClientPool;
    const registry = registryFor('truthcv', 'start_run');

    const result = await executeToolCall(pool, callFor('truthcv__start_run'), registry);

    expect(result.isError).toBe(true);
    expect(result.content.startsWith(content.slice(0, DEFAULT_MAX_TOOL_RESULT_CHARS))).toBe(true);
    expect(result.content).toContain(String(30000 - DEFAULT_MAX_TOOL_RESULT_CHARS));
  });

  it('honours an explicit maxContentChars override instead of the default', async () => {
    const content = 'z'.repeat(100);
    const callTool = vi.fn(async () => ({ content, isError: false }));
    const pool = { callTool } as unknown as McpClientPool;
    const registry = registryFor('truthcv', 'start_run');

    const result = await executeToolCall(pool, callFor('truthcv__start_run'), registry, 50);

    expect(result.content.startsWith('z'.repeat(50))).toBe(true);
    // 100 - 50 = 50 characters omitted, and it is NOT capped at the default.
    expect(result.content).toContain('50');
    expect(result.content).toContain('re-request');
  });
});

describe('buildToolRegistry with screen_and_record_posting', () => {
  it('advertises the compound tool independently of the read-only screen_posting', () => {
    const registry = buildToolRegistry([]);
    expect(registry.find((t) => t.namespacedName === 'screen_and_record_posting')).toMatchObject({
      serverName: 'builtin', toolName: 'screen_and_record_posting',
    });
    expect(registry.find((t) => t.namespacedName === 'screen_posting')).toBeDefined();
  });

  it('requires a live, allow-listed record_screening tool before model work', async () => {
    const pool = { callTool: vi.fn() } as unknown as McpClientPool;
    const adapter = stubScreeningAdapter([doneWithPassingVerdict()]);
    const call: ToolCall = { id: 'save-1', name: 'screen_and_record_posting', arguments: { ...SCREEN_POSTING_ARGS, run_id: 'run-1' } };
    const missing = await executeToolCall(pool, call, buildToolRegistry([]), undefined, undefined, adapter);
    expect(missing.isError).toBe(true);
    expect(missing.content).toContain('not currently available');
    expect(pool.callTool).not.toHaveBeenCalled();
  });

  it('keeps a producer-sized stored outcome parseable under the default cap, including duplicates', async () => {
    const postingText = 'Full posting responsibilities and requirements. '.repeat(1200);
    const producer = (created: boolean) => ({ content: JSON.stringify({
      id: 'persisted-1', url: SCREEN_POSTING_ARGS.url, role: SCREEN_POSTING_ARGS.role,
      company: SCREEN_POSTING_ARGS.company, profile: SCREEN_POSTING_ARGS.profile,
      posting_text: postingText, verdict: 'passed', screening_blocker: '', created,
    }), isError: false });
    const callTool = vi.fn().mockResolvedValueOnce(producer(true)).mockResolvedValueOnce(producer(false));
    const pool = { callTool } as unknown as McpClientPool;
    const call: ToolCall = { id: 'save-1', name: 'screen_and_record_posting',
      arguments: { ...SCREEN_POSTING_ARGS, run_id: 'run-1', postingText } };
    for (const [created, actionable] of [[true, true], [false, false]]) {
      const result = await executeToolCall(pool, call, registryFor('truthcv', 'record_screening'),
        undefined, undefined, stubScreeningAdapter([doneWithPassingVerdict()]));
      expect(result.isError).toBe(false);
      expect(result.content.length).toBeLessThan(DEFAULT_MAX_TOOL_RESULT_CHARS);
      expect(JSON.parse(result.content)).toEqual({ id: 'persisted-1', verdict: 'passed',
        screening_blocker: '', created, actionable });
      expect(result.content).not.toContain('posting_text');
      expect(result.content).not.toContain('omitted');
    }
    expect(callTool).toHaveBeenCalledTimes(2);
  });

  it('resolves the live namespaced recorder and returns the stored verdict, not the proposal', async () => {
    const callTool = vi.fn(async (_name: string, _args: Record<string, unknown>) => ({ content: JSON.stringify({ id: 'id-1', created: true, verdict: 'rejected', failing_criterion: 'remote_model' }), isError: false }));
    const pool = { callTool } as unknown as McpClientPool;
    const call: ToolCall = { id: 'save-1', name: 'screen_and_record_posting', arguments: { ...SCREEN_POSTING_ARGS, run_id: 'run-1' } };
    const result = await executeToolCall(pool, call, registryFor('truthcv', 'record_screening'), undefined, undefined, stubScreeningAdapter([doneWithPassingVerdict()]));
    expect(result.toolCallId).toBe('save-1');
    expect(result.isError).toBe(false);
    expect(JSON.parse(result.content)).toMatchObject({ verdict: 'rejected', actionable: false });
    expect(callTool).toHaveBeenCalledTimes(1);
    expect(callTool.mock.calls[0][0]).toBe('truthcv__record_screening');
  });
});

describe('buildToolRegistry with screen_posting', () => {
  it('advertises screen_posting as a built-in, bare-named tool', () => {
    const registry = buildToolRegistry([]);
    const entry = registry.find((t) => t.namespacedName === 'screen_posting');

    expect(entry).toBeDefined();
    expect(entry?.serverName).toBe('builtin');
    expect(entry?.toolName).toBe('screen_posting');
  });
});

describe('executeToolCall dispatching screen_posting', () => {
  it('never touches pool.callTool and returns the structured verdict', async () => {
    const callTool = vi.fn(() => {
      throw new Error('pool.callTool must not be invoked for screen_posting');
    });
    const pool = { callTool } as unknown as McpClientPool;
    const registry = buildToolRegistry([]);
    const adapter = stubScreeningAdapter([doneWithPassingVerdict()]);
    const call: ToolCall = { id: 'call-1', name: 'screen_posting', arguments: SCREEN_POSTING_ARGS };

    const result = await executeToolCall(pool, call, registry, undefined, undefined, adapter);

    expect(callTool).not.toHaveBeenCalled();
    expect(result.isError).toBe(false);
    expect(JSON.parse(result.content).verdict).toBe('passed');
  });

  // No module-level fallback exists any more (the screening adapter is
  // threaded explicitly by the caller — see loop.ts's RunLoopOptions), so
  // omitting it always means "unconfigured", regardless of what any other
  // test in this file has done.
  it('returns isError without a configured screening adapter, never throwing', async () => {
    const pool = { callTool: vi.fn() } as unknown as McpClientPool;
    const registry = buildToolRegistry([]);
    const call: ToolCall = { id: 'call-1', name: 'screen_posting', arguments: SCREEN_POSTING_ARGS };

    const result = await executeToolCall(pool, call, registry, undefined, undefined, undefined);

    expect(result.isError).toBe(true);
    expect(result.content).toContain('not configured');
  });

  it('returns isError when the argument is simply omitted (same default as explicit undefined)', async () => {
    const pool = { callTool: vi.fn() } as unknown as McpClientPool;
    const registry = buildToolRegistry([]);
    const call: ToolCall = { id: 'call-1', name: 'screen_posting', arguments: SCREEN_POSTING_ARGS };

    const result = await executeToolCall(pool, call, registry);

    expect(result.isError).toBe(true);
    expect(result.content).toContain('not configured');
  });
});

describe('buildToolRegistry with harvest_postings', () => {
  it('advertises harvest_postings as a built-in, bare-named tool', () => {
    const registry = buildToolRegistry([]);
    const entry = registry.find((t) => t.namespacedName === 'harvest_postings');

    expect(entry).toBeDefined();
    expect(entry?.serverName).toBe('builtin');
    expect(entry?.toolName).toBe('harvest_postings');
  });
});

describe('executeToolCall dispatching harvest_postings', () => {
  // harvest_postings logs a real `harvest_postings.mode` stderr line on every
  // call in this block — silence it so the run's stderr stays readable.
  beforeEach(() => {
    vi.spyOn(process.stderr, 'write').mockImplementation(() => true);
  });
  afterEach(() => {
    vi.restoreAllMocks();
  });

  /** A registry advertising harvest_postings plus every browser tool, so the
   * built-in's internal browser calls resolve to real namespaced names. */
  function registryWithBrowserTools(omit: readonly string[] = []): RegisteredTool[] {
    const browserTools: NamespacedTool[] = BROWSER_TOOLS.filter((toolName) => !omit.includes(toolName)).map((toolName) => ({
      namespacedName: `browser__${toolName}`,
      serverName: 'browser',
      toolName,
      description: 'd',
      inputSchema: { type: 'object' },
    }));
    return buildToolRegistry(browserTools as ReturnType<McpClientPool['listTools']>);
  }

  it.each([{ omit: [] as string[] }, { omit: ['browser_tab_close'] }])('serializes full board sequences with optional tab tools omitted: $omit', async ({ omit }) => {
    const previous = process.env.AGENT_BROWSER_SESSIONS;
    process.env.AGENT_BROWSER_SESSIONS = '8';
    // Any attempt to add a connection must fail the test, not silently fall back.
    const extraClient = vi.spyOn(LiveMcpClientPool.prototype, 'connectExtra').mockImplementation(() => {
      throw new Error('extra browser client forbidden');
    });
    let releaseFirst: (() => void) | undefined;
    const firstSnapshot = new Promise<void>((resolve) => { releaseFirst = resolve; });
    const calls: string[] = [];
    let board = '';
    let snapshots = 0;
    const callTool = vi.fn(async (name: string, args: Record<string, unknown>): Promise<BrowserToolResult> => {
      expect(name).not.toContain('browser_tab_');
      calls.push(`${name}:${args.url ?? args.text ?? board}`);
      if (name === 'browser__browser_navigate') {
        board = String(args.url);
        snapshots = 0;
        return { content: 'ok', isError: false };
      }
      if (name === 'browser__browser_snapshot' && snapshots++ === 0) {
        if (board.endsWith('/first')) await firstSnapshot;
        return { content: '- searchbox "Search" [ref=s1]', isError: false };
      }
      if (name === 'browser__browser_snapshot') {
        return { content: '- link "Role" [ref=e1]: https://boards.greenhouse.io/acme/jobs/1', isError: false };
      }
      return { content: 'ok', isError: false };
    });
    const pool = { callTool, connectExtra: vi.fn(() => { throw new Error('extra client'); }) } as unknown as McpClientPool;
    const call: ToolCall = {
      id: 'call-1', name: 'harvest_postings',
      arguments: { boards: [
        { board: 'First', url: 'https://example.com/first', keywords: 'first' },
        { board: 'Second', url: 'https://example.com/second', keywords: 'second' },
      ] },
    };
    try {
      const resultPromise = executeToolCall(pool, call, registryWithBrowserTools(omit));
      // The first snapshot is held: no navigation, tab switch, or second board
      // may begin until the first board's type + final snapshot have finished.
      for (let i = 0; i < 100 && callTool.mock.calls.length < 2; i++) await Promise.resolve();
      expect(callTool).toHaveBeenCalledTimes(2);
      expect(calls).toEqual([
        'browser__browser_navigate:https://example.com/first',
        'browser__browser_snapshot:https://example.com/first',
      ]);
      releaseFirst?.();
      const result = await resultPromise;
      expect(result.isError).toBe(false);
      expect(JSON.parse(result.content).results.map((r: { board: string; outcome: string }) => [r.board, r.outcome]))
        .toEqual([['First', 'searched'], ['Second', 'searched']]);
      expect(calls).toEqual([
        'browser__browser_navigate:https://example.com/first',
        'browser__browser_snapshot:https://example.com/first',
        'browser__browser_type:first',
        'browser__browser_snapshot:https://example.com/first',
        'browser__browser_navigate:https://example.com/second',
        'browser__browser_snapshot:https://example.com/second',
        'browser__browser_type:second',
        'browser__browser_snapshot:https://example.com/second',
      ]);
      expect(extraClient).not.toHaveBeenCalled();
      expect((pool as unknown as { connectExtra: ReturnType<typeof vi.fn> }).connectExtra).not.toHaveBeenCalled();
    } finally {
      releaseFirst?.();
      if (previous === undefined) delete process.env.AGENT_BROWSER_SESSIONS;
      else process.env.AGENT_BROWSER_SESSIONS = previous;
      extraClient.mockRestore();
    }
  });

  it('refuses harvest_postings\' own internal browser calls, without touching pool.callTool, when NOTHING is advertised', async () => {
    // With an EMPTY registry, harvest_postings' internal browserToolCall must
    // report every browser tool unavailable — including the required
    // browser_navigate call the degraded serial path makes FIRST — rather
    // than guessing a namespaced name or reaching pool.callTool for it.
    const callTool = vi.fn(async () => ({ content: 'should not be reached', isError: false }));
    const pool = { callTool } as unknown as McpClientPool;
    const registry = buildToolRegistry([]); // no browser tools advertised at all
    const call: ToolCall = {
      id: 'call-1',
      name: 'harvest_postings',
      arguments: { boards: [{ board: 'Acme', url: 'https://acme.example/jobs' }] },
    };

    const result = await executeToolCall(pool, call, registry);

    expect(result.isError).toBe(false); // harvest_postings itself never throws
    const parsed = JSON.parse(result.content);
    expect(parsed.results[0].outcome).toBe('blocked');
    expect(callTool).not.toHaveBeenCalled();
  });

  it('does not attempt tab tools even when some are advertised', async () => {
    // Optional tab availability never controls production harvest dispatch.
    const callTool = vi.fn(async (name: string): Promise<BrowserToolResult> => {
      if (name === 'browser__browser_navigate') return { content: 'ok', isError: false };
      if (name === 'browser__browser_snapshot') {
        return { content: '- link "Role" [ref=e1]: https://boards.greenhouse.io/acme/jobs/1', isError: false };
      }
      return { content: 'should not be reached: unexpected tab-tool call', isError: true };
    });
    const pool = { callTool } as unknown as McpClientPool;
    const registry = registryWithBrowserTools(['browser_tab_close']);
    const call: ToolCall = {
      id: 'call-1',
      name: 'harvest_postings',
      arguments: { boards: [{ board: 'Acme', url: 'https://acme.example/jobs' }] },
    };

    const result = await executeToolCall(pool, call, registry);

    expect(result.isError).toBe(false);
    expect(callTool.mock.calls.every(([name]) => !String(name).includes('tab'))).toBe(true);
    const parsed = JSON.parse(result.content);
    expect(parsed.results[0].outcome).toBe('searched');
  });

  it('contains a thrown board failure and preserves ordered classification and raw snapshot', async () => {
    let current = '';
    const raw = '- link "Other role" [ref=e2]: https://example.com/careers/role';
    const callTool = vi.fn(async (name: string, args: Record<string, unknown>): Promise<BrowserToolResult> => {
      expect(name).not.toContain('browser_tab_');
      if (name === 'browser__browser_navigate') {
        current = String(args.url);
        if (current.endsWith('/failure')) throw new Error('connection lost');
        return { content: 'ok', isError: false };
      }
      if (name === 'browser__browser_snapshot') {
        const content = current.endsWith('/found')
          ? '- link "Engineer" [ref=e1]: https://jobs.lever.co/acme/role-1\nComplete the CAPTCHA'
          : current.endsWith('/raw') ? raw : 'sign in to continue';
        return { content, isError: false };
      }
      return { content: 'unexpected tool', isError: true };
    });
    const pool = { callTool } as unknown as McpClientPool;
    const boards = ['failure', 'found', 'raw', 'login'].map((name) => ({ board: name, url: `https://example.com/${name}` }));
    const result = await executeToolCall(pool, {
      id: 'call-1', name: 'harvest_postings', arguments: { boards },
    }, registryWithBrowserTools());
    expect(result.isError).toBe(false);
    const parsed = JSON.parse(result.content).results;
    expect(parsed.map((r: { board: string; outcome: string }) => [r.board, r.outcome])).toEqual([
      ['failure', 'blocked'], ['found', 'searched'], ['raw', 'needs_review'], ['login', 'blocked'],
    ]);
    expect(parsed[0]).toMatchObject({ note: expect.stringContaining('connection lost'), postings: [] });
    expect(parsed[0].blockKind).toBeUndefined();
    expect(parsed[1]).toMatchObject({ tier: 'harvest', postings: [{ ats: 'lever', title: 'Engineer' }] });
    expect(parsed[2]).toMatchObject({ rawSnapshot: raw });
    expect(parsed[3]).toMatchObject({ blockKind: 'login', postings: [] });
    expect(parsed[3].rawSnapshot).toBeUndefined();
    expect(callTool.mock.calls.map(([name, args]) => [name, args.url ?? ''])).toEqual([
      ['browser__browser_navigate', 'https://example.com/failure'],
      ['browser__browser_navigate', 'https://example.com/found'],
      ['browser__browser_snapshot', ''],
      ['browser__browser_navigate', 'https://example.com/raw'],
      ['browser__browser_snapshot', ''],
      // Sign-in URLs are refused before any browser navigation.

    ]);
  });
});

describe('checkAdvertisedBrowserTools', () => {
  /** Build a raw namespaced-tool list for the given (server, tool) pairs. */
  function toolsList(pairs: [string, string][]): ReturnType<McpClientPool['listTools']> {
    const tools: NamespacedTool[] = pairs.map(([serverName, toolName]) => ({
      namespacedName: `${serverName}__${toolName}`,
      serverName,
      toolName,
      description: 'd',
      inputSchema: { type: 'object' },
    }));
    return tools as ReturnType<McpClientPool['listTools']>;
  }

  it('returns [] when every allowlisted browser tool is advertised', () => {
    const advertised = toolsList(BROWSER_TOOLS.map((name) => ['browser', name] as [string, string]));
    expect(checkAdvertisedBrowserTools(advertised)).toEqual([]);
  });

  it('returns the missing tool name when the browser server drops a REQUIRED one', () => {
    const advertised = toolsList(
      BROWSER_TOOLS.filter((name) => name !== 'browser_snapshot').map(
        (name) => ['browser', name] as [string, string],
      ),
    );
    const missing = checkAdvertisedBrowserTools(advertised);
    expect(missing).toContain('browser_snapshot');
  });

  it('does not report a missing OPTIONAL tab tool as missing — its absence must not fail startup', () => {
    const advertised = toolsList(
      BROWSER_TOOLS.filter((name) => name !== 'browser_tab_new').map(
        (name) => ['browser', name] as [string, string],
      ),
    );
    expect(checkAdvertisedBrowserTools(advertised)).toEqual([]);
  });
});
