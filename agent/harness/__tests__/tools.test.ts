import { describe, it, expect, vi } from 'vitest';
import type { McpClientPool, NamespacedTool } from '../mcp/client.js';
import type { ToolCall } from '../providers/types.js';
import {
  buildToolRegistry,
  checkAdvertisedBrowserTools,
  DEFAULT_MAX_TOOL_RESULT_CHARS,
  executeToolCall,
  isToolAllowed,
  type RegisteredTool,
} from '../tools.js';

/** The 10 browser tools enumerated in the browser allow-list. */
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
];

/** The 18 truthcv tools granted individually by daily-apply.sh. */
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
  it('grants every one of the 18 named truthcv tools', () => {
    for (const name of TRUTHCV_TOOLS) {
      expect(isToolAllowed('truthcv', name)).toBe(true);
    }
  });

  it('denies an unlisted truthcv tool', () => {
    expect(isToolAllowed('truthcv', 'delete_everything')).toBe(false);
    expect(isToolAllowed('truthcv', 'some_unlisted_18th_tool')).toBe(false);
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

  it('returns the missing tool name when the browser server drops one', () => {
    const advertised = toolsList(
      BROWSER_TOOLS.filter((name) => name !== 'browser_snapshot').map(
        (name) => ['browser', name] as [string, string],
      ),
    );
    const missing = checkAdvertisedBrowserTools(advertised);
    expect(missing).toContain('browser_snapshot');
  });
});
