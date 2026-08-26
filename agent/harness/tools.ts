/**
 * The merged tool registry and the single permission choke point every tool
 * call in the harness passes through.
 *
 * This allow-list IS the harness's sole authorization boundary over its own
 * MCP tool surface — the enforcement lives here, in this file, not in any
 * external CLI flag. There is deliberately no interactive approver: this is an
 * unattended run whose stdin is `/dev/null`, so it cannot block on an approval
 * prompt. With no prompt to fall back on, the allow-list below, and nothing
 * else, decides what may be called — it is the complete authorization boundary.
 *
 * This harness has NO built-in tools of its own — no Read, Write, WebSearch or
 * WebFetch — so only MCP tools exist to be granted, and the enumerated list
 * below is deliberate and exhaustive.
 */

import type { NamespacedTool, McpClientPool } from './mcp/client.js';
import type { ToolCall, ToolDefinition, ToolResult } from './providers/types.js';

/**
 * The 17 truthcv tools granted individually by `daily-apply.sh`, as their bare
 * (un-namespaced) tool names.
 *
 * These are enumerated one by one ON PURPOSE: naming each tool keeps the blast
 * radius of a newly added server-side tool at ZERO until it is explicitly
 * granted here, so a new tool appearing on the truthcv MCP server cannot be
 * called by the agent until someone adds it to this list on purpose.
 */
const TRUTHCV_ALLOWED_TOOL_NAMES = [
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
] as const;

/** The MCP server key of the truthcv tool surface the named grants apply to. */
const TRUTHCV_SERVER_NAME = 'truthcv';

/**
 * The browser server, granted as a WHOLE server rather than as an enumerated
 * tool list.
 *
 * Any tool whose server is `browser` is allowed. This is granted whole ON
 * PURPOSE: the browser server is upstream `@playwright/mcp`, which renames and
 * extends its own tools on version bumps. Pinning individual browser tool names
 * here would silently disable whichever tool got renamed, mid-run, in an
 * unattended job — so the whole server is trusted and containment comes from
 * the container instead.
 */
const BROWSER_SERVER_NAME = 'browser';

/**
 * Tools explicitly denied even if the allow-list would grant them.
 *
 * Empty today — there is nothing to explicitly deny yet — but the choke point
 * checks it after the allow decision so a deny-list can be added later without
 * restructuring {@link isToolAllowed}.
 */
const DENY_LIST: readonly string[] = [];

/**
 * One tool exposed to the model, keyed by its collision-free namespaced name.
 *
 * Carries the owning server and bare tool name (for permission decisions) plus
 * the {@link ToolDefinition} a provider adapter consumes directly.
 */
export interface RegisteredTool {
  /** The unique namespaced name the model and the pool both use. */
  namespacedName: string;
  /** The MCP server that owns the tool. */
  serverName: string;
  /** The tool's own (un-namespaced) name. */
  toolName: string;
  /** The provider-facing definition of the tool. */
  definition: ToolDefinition;
}

/**
 * Map the pool's namespaced tools into a registry of {@link RegisteredTool}s.
 *
 * Each entry's {@link ToolDefinition} uses the namespaced name as its `name`,
 * so the shape can be handed straight to any provider adapter.
 *
 * @param mcpTools The pool's {@link McpClientPool.listTools} output.
 * @returns One {@link RegisteredTool} per input tool, order preserved.
 */
export function buildToolRegistry(mcpTools: ReturnType<McpClientPool['listTools']>): RegisteredTool[] {
  return mcpTools.map((tool: NamespacedTool) => ({
    namespacedName: tool.namespacedName,
    serverName: tool.serverName,
    toolName: tool.toolName,
    definition: {
      name: tool.namespacedName,
      description: tool.description,
      inputSchema: tool.inputSchema,
    },
  }));
}

/**
 * Decide whether a (server, tool) pair may be called, reproducing exactly
 * `daily-apply.sh`'s allow-list policy.
 *
 * Allow-list first, then deny-list: the whole `browser` server is granted, a
 * truthcv tool is granted only if its bare name is in
 * {@link TRUTHCV_ALLOWED_TOOL_NAMES}, and anything else is denied. A pair the
 * allow-list would grant is still refused if it appears in {@link DENY_LIST}.
 *
 * @param serverName The owning MCP server key.
 * @param toolName The tool's own (un-namespaced) name.
 * @returns True if the tool may be called.
 */
export function isToolAllowed(serverName: string, toolName: string): boolean {
  if (DENY_LIST.includes(toolName)) return false;
  if (serverName === BROWSER_SERVER_NAME) return true;
  const truthcvAllowed = (TRUTHCV_ALLOWED_TOOL_NAMES as readonly string[]).includes(toolName);
  return serverName === TRUTHCV_SERVER_NAME && truthcvAllowed;
}

/**
 * The ONE choke point every tool call passes through.
 *
 * Looks the call up by its namespaced name in the registry. An unknown tool,
 * or one the allow-list denies, returns an `isError` {@link ToolResult}
 * WITHOUT touching `pool.callTool` and without throwing — so an unattended run
 * continues and the model sees, in the result, why the call was refused. An
 * allowed call is dispatched and its `{content, isError}` mapped to a
 * {@link ToolResult}.
 *
 * @param pool The MCP client pool to dispatch allowed calls through.
 * @param call The model's requested tool call.
 * @param registry The registry from {@link buildToolRegistry}.
 * @returns The result to feed back to the model.
 */
export async function executeToolCall(
  pool: McpClientPool,
  call: ToolCall,
  registry: RegisteredTool[],
): Promise<ToolResult> {
  const tool = registry.find((t) => t.namespacedName === call.name);
  if (!tool) {
    return { toolCallId: call.id, content: `Unknown tool: '${call.name}' is not registered.`, isError: true };
  }
  if (!isToolAllowed(tool.serverName, tool.toolName)) {
    return { toolCallId: call.id, content: `Tool '${call.name}' is not permitted by the allow-list.`, isError: true };
  }
  const result = await pool.callTool(tool.namespacedName, call.arguments);
  return { toolCallId: call.id, content: result.content, isError: result.isError };
}
