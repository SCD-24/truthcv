import { describe, it, expect, vi } from 'vitest';
import type { McpClientPool, NamespacedTool } from '../mcp/client.js';
import type { ToolCall } from '../providers/types.js';
import { buildToolRegistry, executeToolCall, isToolAllowed, type RegisteredTool } from '../tools.js';

/** The 17 truthcv tools granted individually by daily-apply.sh. */
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
  it('grants every one of the 17 named truthcv tools', () => {
    for (const name of TRUTHCV_TOOLS) {
      expect(isToolAllowed('truthcv', name)).toBe(true);
    }
  });

  it('denies an unlisted truthcv tool', () => {
    expect(isToolAllowed('truthcv', 'delete_everything')).toBe(false);
    expect(isToolAllowed('truthcv', 'some_unlisted_18th_tool')).toBe(false);
  });

  it('grants any tool at all from the browser server as a whole-server grant', () => {
    expect(isToolAllowed('browser', 'browser_navigate')).toBe(true);
    expect(isToolAllowed('browser', 'browser_click')).toBe(true);
    expect(isToolAllowed('browser', 'browser_totally_new_tool')).toBe(true);
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

  it('allows any browser tool through the whole-server grant', async () => {
    const callTool = vi.fn(async () => ({ content: 'navigated', isError: false }));
    const pool = { callTool } as unknown as McpClientPool;
    const registry = registryFor('browser', 'browser_totally_new_tool');

    const result = await executeToolCall(pool, callFor('browser__browser_totally_new_tool'), registry);

    expect(callTool).toHaveBeenCalledWith('browser__browser_totally_new_tool', {});
    expect(result.content).toBe('navigated');
  });
});
