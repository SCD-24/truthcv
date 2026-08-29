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
 * This harness has almost NO built-in tools of its own — no Read, Write,
 * WebSearch or WebFetch. The one narrow exception is `read_runbook_section`
 * (see ./builtins/readRunbook.ts): it reads exactly ONE fixed file, the
 * agent's RUNBOOK, exposes no file-path argument, and grants no general
 * filesystem access. Every OTHER capability the agent has is an MCP tool, and
 * the enumerated allow-list below is the deliberate, exhaustive authorization
 * boundary over that MCP surface.
 */

import { fileURLToPath } from 'node:url';
import { dirname, join } from 'node:path';
import type { NamespacedTool, McpClientPool } from './mcp/client.js';
import type { ToolCall, ToolDefinition, ToolResult } from './providers/types.js';
import { readRunbookSection, readRunbookSectionTool } from './builtins/readRunbook.js';

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
 * The browser server, now granted as an enumerated allow-list of tool names
 * ({@link BROWSER_ALLOWED_TOOL_NAMES}) rather than as a whole-server grant.
 *
 * This used to be a WHOLE-server grant. It is now an enumerated allow-list like
 * the truthcv one — kept in `mcp.json`'s `browser.allowedTools` and mirrored
 * here for the {@link isToolAllowed} check. The browser server is upstream
 * `@playwright/mcp`, which renames and extends its own tools on version bumps;
 * containment still comes from the container, but the surface the agent may
 * actually call is now narrowed to the tools its RUNBOOK depends on.
 */
const BROWSER_SERVER_NAME = 'browser';

/**
 * The browser tools the agent's RUNBOOK (agent/RUNBOOK.md) actually instructs
 * it to call, as their bare (un-namespaced) tool names.
 *
 * Unlike the truthcv list, the browser server USED TO BE a whole-server grant.
 * Narrowing it to this enumerated set is what makes {@link isToolAllowed}
 * filterable for the browser server and keeps the advertised tool list small
 * enough to hold the cached prompt prefix stable session to session. This list
 * is kept in `mcp.json`'s `browser.allowedTools` and mirrored here for the
 * {@link isToolAllowed} check.
 */
const BROWSER_ALLOWED_TOOL_NAMES = [
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
] as const;

/**
 * Tools explicitly denied even if the allow-list would grant them.
 *
 * Empty today — there is nothing to explicitly deny yet — but the choke point
 * checks it after the allow decision so a deny-list can be added later without
 * restructuring {@link isToolAllowed}.
 */
const DENY_LIST: readonly string[] = [];

/**
 * The default cap, in characters, on a SINGLE tool result's content.
 *
 * Applied at INSERTION — the moment {@link executeToolCall} produces a fresh
 * result — so one oversized MCP response (a full-page browser snapshot, a long
 * file read) cannot dominate the context window or blow up the Anthropic
 * prompt-cache prefix cost by shoving everything after it past the cached
 * boundary. This is only a default: callers (loop.ts, and eventually cli.ts's
 * config) may override it by passing an explicit `maxContentChars`. It is NEVER
 * read from `process.env` inside this file — the cap is a plain parameter so
 * its value is always visible at the call site.
 */
export const DEFAULT_MAX_TOOL_RESULT_CHARS = 24000;

/**
 * Builds the marker appended in place of the characters a capped tool result
 * dropped, naming exactly how many were omitted and telling the model what to
 * do about it.
 *
 * Styled after cli.ts's private `TRUNCATION_MARKER`, but distinct on purpose:
 * this one states the omitted character COUNT and instructs the model to
 * re-request a narrower view (a smaller limit, a more targeted snapshot or
 * selector) rather than silently losing the tail. It is a function, not a
 * constant, because the count is only known per-result.
 *
 * @param omitted The number of characters dropped from the end of the content.
 * @returns The marker string to append to the truncated content.
 */
function toolResultTruncationMarker(omitted: number): string {
  return `\n\n…[${omitted} characters omitted — re-request a narrower view: a smaller limit, or a more targeted snapshot/selector]`;
}

/**
 * Cap `content` at `maxChars`, appending {@link toolResultTruncationMarker}
 * when it is cut.
 *
 * Content at or under the cap is returned UNCHANGED — the exact same string,
 * no marker, no allocation-visible difference. Over the cap, a `maxChars`
 * prefix is kept and the marker (naming the omitted count) is appended. Slicing
 * at a fixed offset can split a surrogate pair, leaving a lone high surrogate;
 * as in cli.ts's `truncate`, a trailing unpaired high surrogate is dropped so
 * the result stays well-formed (`toWellFormed` is ES2024; this package
 * compiles against the ES2022 lib, so the check is written out).
 *
 * @param content The freshly produced tool result content.
 * @param maxChars The cap, in characters (UTF-16 code units).
 * @returns `content` unchanged, or a well-formed prefix plus the marker.
 */
function capToolResultContent(content: string, maxChars: number): string {
  if (content.length <= maxChars) return content;
  const cut = content.slice(0, maxChars);
  const last = cut.charCodeAt(cut.length - 1);
  const splitPair = last >= 0xd800 && last <= 0xdbff;
  const kept = splitPair ? cut.slice(0, -1) : cut;
  return `${kept}${toolResultTruncationMarker(content.length - kept.length)}`;
}

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
 * The synthetic server identity for the harness's one built-in tool. It is not
 * an MCP server: no entry in `mcp.json`, no client in the pool. The label only
 * populates {@link RegisteredTool.serverName} so the shape is uniform; the
 * allow-list ({@link isToolAllowed}) never grants this label, because the
 * built-in bypasses that check entirely in {@link executeToolCall}.
 */
const BUILTIN_SERVER_NAME = 'builtin';

/**
 * The registry entry for the built-in {@link readRunbookSectionTool}. It has no
 * `mcp__` prefix because it is not MCP-backed: its `namespacedName` is the bare
 * tool name, which sorts as a plain string alongside the namespaced MCP tools
 * in {@link buildToolRegistry}. Its `definition.name` equals the namespaced
 * name, exactly as the MCP entries maintain.
 */
const READ_RUNBOOK_SECTION_TOOL: RegisteredTool = {
  namespacedName: readRunbookSectionTool.name,
  serverName: BUILTIN_SERVER_NAME,
  toolName: readRunbookSectionTool.name,
  definition: readRunbookSectionTool,
};

/**
 * Default path to the RUNBOOK the built-in reads, resolved relative to THIS
 * compiled file rather than the process cwd. In the built image this file is
 * `/app/agent/dist/harness/tools.js`, so two levels up lands on
 * `/app/agent/RUNBOOK.md`; the Dockerfile copies the RUNBOOK to exactly that
 * path. {@link executeToolCall} defaults to it but accepts an override so tests
 * can point elsewhere.
 */
const DEFAULT_RUNBOOK_PATH = join(dirname(fileURLToPath(import.meta.url)), '..', '..', 'RUNBOOK.md');

/**
 * Map the pool's namespaced tools into a registry of {@link RegisteredTool}s,
 * filtered through the allow-list and sorted for a stable prompt prefix.
 *
 * The model only ever sees tools the allow-list grants: every input tool is
 * first filtered through {@link isToolAllowed}, so this is a second,
 * defense-in-depth safety net matching the `isToolAllowed` check
 * {@link executeToolCall} already enforces at call time — but now it also
 * shapes what is ADVERTISED, not just what is dispatchable. The surviving tools
 * are then sorted by `namespacedName`, which is what keeps the advertised tool
 * block byte-stable turn over turn even if the underlying MCP pool re-lists its
 * tools in a different order. That matters because loop.ts's `refreshRegistry`
 * rebuilds this registry fresh every single turn, and a reordered tool block
 * would invalidate the Anthropic prompt cache set up elsewhere in this change.
 *
 * Each entry's {@link ToolDefinition} uses the namespaced name as its `name`,
 * so the shape can be handed straight to any provider adapter.
 *
 * @param mcpTools The pool's {@link McpClientPool.listTools} output.
 * @returns One {@link RegisteredTool} per allowed input tool, sorted by
 *   `namespacedName` ascending.
 */
export function buildToolRegistry(mcpTools: ReturnType<McpClientPool['listTools']>): RegisteredTool[] {
  const mcp = mcpTools
    .filter((tool: NamespacedTool) => isToolAllowed(tool.serverName, tool.toolName))
    .map((tool: NamespacedTool) => ({
      namespacedName: tool.namespacedName,
      serverName: tool.serverName,
      toolName: tool.toolName,
      definition: {
        name: tool.namespacedName,
        description: tool.description,
        inputSchema: tool.inputSchema,
      },
    }));
  // Advertise the built-in RUNBOOK reader alongside the MCP-derived tools. It
  // is appended AFTER the allow-list filter (which would deny its synthetic
  // server) and before the sort, so the advertised block stays byte-stable.
  return [...mcp, READ_RUNBOOK_SECTION_TOOL].sort((a, b) =>
    a.namespacedName.localeCompare(b.namespacedName),
  );
}

/**
 * Given the pool's raw (unfiltered) tool list, return which
 * {@link BROWSER_ALLOWED_TOOL_NAMES} are ABSENT from the tools actually
 * advertised by the `browser` server. An empty array means all are present.
 *
 * This exists so a call site can fail loudly, at startup, if an upstream
 * `@playwright/mcp` rename silently drops a tool this agent's RUNBOOK depends
 * on — instead of the agent finding out mid-run when, say, a `browser_snapshot`
 * call comes back as "unknown tool".
 *
 * @param mcpTools The pool's raw {@link McpClientPool.listTools} output.
 * @returns The allowlisted browser tool names the browser server does not
 *   advertise; empty when every one is present.
 */
export function checkAdvertisedBrowserTools(mcpTools: ReturnType<McpClientPool['listTools']>): string[] {
  return BROWSER_ALLOWED_TOOL_NAMES.filter(
    (name) =>
      !mcpTools.some((tool) => tool.serverName === BROWSER_SERVER_NAME && tool.toolName === name),
  );
}

/**
 * Decide whether a (server, tool) pair may be called, reproducing exactly
 * `daily-apply.sh`'s allow-list policy.
 *
 * Allow-list first, then deny-list: a `browser` tool is granted only if its
 * bare name is in {@link BROWSER_ALLOWED_TOOL_NAMES}, a truthcv tool is granted
 * only if its bare name is in {@link TRUTHCV_ALLOWED_TOOL_NAMES}, and anything
 * else is denied. A pair the allow-list would grant is still refused if it
 * appears in {@link DENY_LIST}.
 *
 * @param serverName The owning MCP server key.
 * @param toolName The tool's own (un-namespaced) name.
 * @returns True if the tool may be called.
 */
export function isToolAllowed(serverName: string, toolName: string): boolean {
  if (DENY_LIST.includes(toolName)) return false;
  if (serverName === BROWSER_SERVER_NAME) return (BROWSER_ALLOWED_TOOL_NAMES as readonly string[]).includes(toolName);
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
 * {@link ToolResult}, with the dispatched content — success OR error body —
 * capped at `maxContentChars` via {@link capToolResultContent} so a single
 * oversized MCP response cannot dominate the context window. The two synthetic
 * refusal strings above (unknown tool, not permitted) are short human-authored
 * messages and are deliberately left uncapped.
 *
 * @param pool The MCP client pool to dispatch allowed calls through.
 * @param call The model's requested tool call.
 * @param registry The registry from {@link buildToolRegistry}.
 * @param maxContentChars Cap on the dispatched result's content, in characters.
 *   Defaults to {@link DEFAULT_MAX_TOOL_RESULT_CHARS}. A plain parameter, never
 *   read from `process.env` here — callers pass the value they want enforced.
 * @returns The result to feed back to the model.
 */
export async function executeToolCall(
  pool: McpClientPool,
  call: ToolCall,
  registry: RegisteredTool[],
  maxContentChars: number = DEFAULT_MAX_TOOL_RESULT_CHARS,
  runbookPath: string = DEFAULT_RUNBOOK_PATH,
): Promise<ToolResult> {
  const tool = registry.find((t) => t.namespacedName === call.name);
  if (!tool) {
    return { toolCallId: call.id, content: `Unknown tool: '${call.name}' is not registered.`, isError: true };
  }
  // The built-in RUNBOOK reader is dispatched here, BEFORE the allow-list and
  // WITHOUT touching the MCP pool: it is not MCP-backed, reads exactly one
  // fixed file, and is always allowed. Its content is still passed through the
  // same cap as MCP results so a huge section cannot dominate the context.
  if (tool.namespacedName === READ_RUNBOOK_SECTION_TOOL.namespacedName) {
    const section = typeof call.arguments.section === 'string' ? call.arguments.section : '';
    const result = await readRunbookSection({ section }, runbookPath);
    return {
      toolCallId: call.id,
      content: capToolResultContent(result.content, maxContentChars),
      isError: result.isError,
    };
  }
  if (!isToolAllowed(tool.serverName, tool.toolName)) {
    return { toolCallId: call.id, content: `Tool '${call.name}' is not permitted by the allow-list.`, isError: true };
  }
  const result = await pool.callTool(tool.namespacedName, call.arguments);
  return {
    toolCallId: call.id,
    content: capToolResultContent(result.content, maxContentChars),
    isError: result.isError,
  };
}
