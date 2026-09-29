/**
 * Code-driven pipeline CLI (`node dist/harness/pipeline/pipelineCli.js <cmd>`).
 *
 * Subcommands:
 *  - `start`            start_run + check_gmail_responses + get_approved_applications -> `--out` JSON.
 *  - `discover-screen`  discover, fetch, extract, screen; writes actionable passes to `--out`.
 *  - `stage-prompt <s>` print a stage's static system prompt to stdout.
 *  - `finish`           finish_run: `completed` = no systemic failure; per-item failures are counted.
 *
 * Model routing and MCP config are the same as cli.ts (`--routes-file`,
 * `--mcp-config`, `--screening-*`). Exit codes follow cli.ts: 0 ok, 3 a stage
 * failed, 4 MCP unavailable, 5 bad arguments/configuration.
 */
import { readFile, writeFile } from 'node:fs/promises';
import { ExitCode, parseArgs, redactAll, resolveConfig, validateConfig, type CliConfig } from '../cli.js';
import { loadMcpConfig, type McpServerConfig } from '../mcp/config.js';
import { createMcpClientPool, type McpClientPool } from '../mcp/client.js';
import { createProviderAdapter, type ProviderAdapterOptions } from '../providers/registry.js';
import type { ProviderAdapter } from '../providers/types.js';
import type { BrowserToolCall } from '../builtins/harvestTypes.js';
import { STAGE_REGISTRY, type StageName } from '../stages.js';
import { discover } from './discover.js';
import { fetchPosting } from './fetchPosting.js';
import { screenCandidates } from './screenStage.js';
import { composeStagePrompt, defaultAgentDir } from './stagePrompt.js';
import type { McpCall } from './types.js';

/** Server name of the browser MCP server. */
const BROWSER_SERVER = 'browser';
/** Max characters of a stopped_reason. */
const MAX_STOPPED_REASON_CHARS = 240;

/** Injectable dependencies (defaults are the real implementations). */
export interface PipelineDeps {
  createPool?: (servers: McpServerConfig[]) => Promise<McpClientPool>;
  loadConfig?: (path: string, env: NodeJS.ProcessEnv) => McpServerConfig[];
  createAdapter?: (opts: ProviderAdapterOptions) => ProviderAdapter;
  readFileText?: (path: string) => Promise<string>;
  writeOutput?: (path: string, text: string) => Promise<void>;
  stdout?: (line: string) => void;
  stderr?: (line: string) => void;
}

type Resolved = Required<PipelineDeps>;

/** The parsed subcommand line. */
export interface PipelineArgs {
  command: string;
  flags: Record<string, string>;
  positional: string[];
}

/** Split argv into the subcommand, its flags and positionals. */
export function parsePipelineArgs(argv: string[]): PipelineArgs {
  const [command = '', ...rest] = argv;
  const parsed = parseArgs(rest);
  return { command, flags: parsed.flags, positional: parsed.positional };
}

function withDefaults(d: PipelineDeps): Resolved {
  return {
    createPool: d.createPool ?? ((servers) => createMcpClientPool(servers)),
    loadConfig: d.loadConfig ?? loadMcpConfig,
    createAdapter: d.createAdapter ?? createProviderAdapter,
    readFileText: d.readFileText ?? ((p) => readFile(p, 'utf8')),
    writeOutput: d.writeOutput ?? ((p, t) => writeFile(p, t, 'utf8')),
    stdout: d.stdout ?? ((l) => void process.stdout.write(`${l}\n`)),
    stderr: d.stderr ?? ((l) => void process.stderr.write(`${l}\n`)),
  };
}

/** An MCP tool caller over the pool, by bare tool name (never the browser server). */
function mcpCaller(pool: McpClientPool): McpCall {
  return async (tool, args) => {
    const target = pool.listTools().find((t) => t.toolName === tool && t.serverName !== BROWSER_SERVER);
    if (!target) return { content: `tool '${tool}' is not available`, isError: true };
    const res = await pool.callTool(target.namespacedName, args);
    return { content: res.content, isError: res.isError === true };
  };
}

/** A browser tool caller over the pool, by bare tool name. */
function browserCaller(pool: McpClientPool): BrowserToolCall {
  return async (tool, args) => {
    const target = pool.listTools().find((t) => t.serverName === BROWSER_SERVER && t.toolName === tool);
    if (!target) return { content: `Browser tool '${tool}' is not currently available.`, isError: true };
    const res = await pool.callTool(target.namespacedName, args);
    return { content: res.content, isError: res.isError === true };
  };
}

/** Connect the MCP pool, or undefined when it cannot be brought up. */
async function connect(a: PipelineArgs, env: NodeJS.ProcessEnv, d: Resolved): Promise<McpClientPool | undefined> {
  try {
    const pool = await d.createPool(d.loadConfig(a.flags['mcp-config'] ?? env.MCP_CONFIG_PATH ?? 'mcp.json', env));
    return pool.listTools().length > 0 ? pool : undefined;
  } catch {
    return undefined;
  }
}

/** Whether a tool result failed: an MCP error, or a parsed `{recorded:false}` / `{ok:false}`. */
function failed(res: { content: string; isError: boolean }): boolean {
  if (res.isError) return true;
  try {
    const v = JSON.parse(res.content) as { recorded?: unknown; ok?: unknown } | null;
    return !!v && typeof v === 'object' && (v.recorded === false || v.ok === false);
  } catch {
    return false;
  }
}

/** Args for get_approved_applications: lease to this run and apply the server cap when known. */
function approvedArgs(runId: string, limit: string | undefined): Record<string, unknown> {
  const n = Number(limit);
  return Number.isInteger(n) && n > 0 ? { run_id: runId, limit: n } : { run_id: runId };
}

/** `start`: open the run, check Gmail, and save the approved queue. */
async function cmdStart(a: PipelineArgs, mcp: McpCall, d: Resolved): Promise<number> {
  const runId = a.flags['run-id'];
  const out = a.flags.out;
  if (!runId || !out) return fail(d, 'start requires --run-id and --out', ExitCode.BadConfig);
  const started = await mcp('start_run', { run_id: runId, trigger: a.flags.trigger ?? 'scheduled' });
  if (failed(started)) return fail(d, `start_run failed: ${started.content}`, ExitCode.ProviderError);
  const gmail = await mcp('check_gmail_responses', {});
  if (gmail.isError) d.stderr(`check_gmail_responses failed: ${gmail.content}`);
  const approved = await mcp('get_approved_applications', approvedArgs(runId, a.flags.limit));
  if (approved.isError) return fail(d, `get_approved_applications failed: ${approved.content}`, ExitCode.ProviderError);
  await d.writeOutput(out, approved.content);
  return ExitCode.Success;
}

/** Build one stage's adapter from the resolved routes. */
function stageAdapter(config: CliConfig, stage: StageName, d: Resolved): ProviderAdapter {
  const r = config.stageRoutes![stage];
  return d.createAdapter({
    provider: r.provider, wire: r.wire, model: r.model, token: r.token, baseUrl: r.baseUrl,
    authType: r.authType, promptCache: config.promptCache,
  });
}

/** Resolve and validate model config (same path as cli.ts). */
async function loadConfig(a: PipelineArgs, env: NodeJS.ProcessEnv, d: Resolved): Promise<CliConfig | string> {
  const parsed = { flags: a.flags, positional: ['pipeline'] };
  const config = await resolveConfig(parsed, env, { readFileText: d.readFileText, readStdin: async () => '' });
  const errors = validateConfig(config);
  return errors.length ? errors.join('; ') : config;
}

/** All resolved stage tokens, for redaction. */
function tokensOf(config: CliConfig): string[] {
  const t = Object.values(config.stageRoutes ?? {}).map((r) => r.token);
  return [...new Set([config.token, config.screeningToken, ...t])].filter(Boolean);
}

/** `discover-screen`: discovery, fetch, extract and screening. */
async function cmdDiscoverScreen(a: PipelineArgs, env: NodeJS.ProcessEnv, pool: McpClientPool, d: Resolved, config: CliConfig): Promise<number> {
  const { 'run-id': runId, 'job-config': jobPath, criteria: critPath, out } = a.flags;
  if (!runId || !jobPath || !critPath || !out) {
    return fail(d, 'discover-screen requires --run-id, --job-config, --criteria and --out', ExitCode.BadConfig);
  }
  const jobConfig = JSON.parse(await d.readFileText(jobPath)) as Record<string, unknown>;
  const criteria = JSON.parse(await d.readFileText(critPath)) as Record<string, string>;
  const mcp = mcpCaller(pool);
  const browser = browserCaller(pool);
  const found = await discover(jobConfig, runId, browser, mcp);
  const screened = await screenCandidates(found.candidates, {
    runId, criteria, fetch: (url) => fetchPosting(browser, url),
    extractAdapter: stageAdapter(config, 'extract', d),
    screeningAdapter: stageAdapter(config, 'screening', d),
    record: (args) => mcp('record_screening', args),
  });
  const ok = found.coverageComplete && found.errors.length === 0;
  await d.writeOutput(out, JSON.stringify({
    ok, coverageComplete: found.coverageComplete, errors: found.errors, itemErrors: screened.errors.map((e) => redactAll(e, tokensOf(config))),
    blockers: screened.blockers, passes: screened.passes,
  }));
  d.stderr(JSON.stringify({ event: 'discover-screen', ok, itemErrors: screened.errors.length, errors: found.errors.length }));
  return ok ? ExitCode.Success : ExitCode.ProviderError;
}

/** `stage-prompt <stage>`: print a stage's static system prompt. */
async function cmdStagePrompt(a: PipelineArgs, d: Resolved): Promise<number> {
  const stage = a.positional[0];
  if (!STAGE_REGISTRY.some((s) => s.name === stage)) return fail(d, `unknown stage '${stage ?? ''}'`, ExitCode.BadConfig);
  try {
    d.stdout(await composeStagePrompt(stage as StageName, a.flags['agent-dir'] ?? defaultAgentDir()));
    return ExitCode.Success;
  } catch (err) {
    return fail(d, err instanceof Error ? err.message : String(err), ExitCode.BadConfig);
  }
}

/** Why the run cannot be called completed, or '' when it can. */
async function incompleteReason(a: PipelineArgs, d: Resolved): Promise<string> {
  const reasons: string[] = [];
  if (a.flags.issues) reasons.push(a.flags.issues);
  if (a.flags['state-file']) {
    // Systemic only (s.ok / s.errors); per-item itemErrors never fail the run.
    try {
      const s = JSON.parse(await d.readFileText(a.flags['state-file'])) as { ok?: boolean; errors?: string[] };
      if (s.ok !== true) reasons.push(`discovery/screening incomplete: ${(s.errors ?? []).join('; ') || 'not ok'}`);
    } catch {
      reasons.push('discovery/screening state unreadable');
    }
  }
  return reasons.join(' | ').slice(0, MAX_STOPPED_REASON_CHARS);
}

/** Per-item failures recorded by discover-screen in the state file (missing/unreadable -> []). */
async function stateItemErrors(a: PipelineArgs, d: Resolved): Promise<string[]> {
  if (!a.flags['state-file']) return [];
  try {
    const s = JSON.parse(await d.readFileText(a.flags['state-file'])) as { itemErrors?: unknown };
    return Array.isArray(s.itemErrors) ? s.itemErrors.map(String) : [];
  } catch {
    return [];
  }
}

/** Per-item apply failures, one per line (file absent/empty -> []). */
async function applyFailuresOf(a: PipelineArgs, d: Resolved): Promise<string[]> {
  const f = a.flags['apply-failures-file'];
  if (!f) return [];
  try {
    return (await d.readFileText(f)).split('\n').map((l) => l.trim()).filter(Boolean);
  } catch {
    return [];
  }
}

/** `finish`: close the run honestly. */
async function cmdFinish(a: PipelineArgs, mcp: McpCall, d: Resolved, env: NodeJS.ProcessEnv): Promise<number> {
  const runId = a.flags['run-id'];
  if (!runId) return fail(d, 'finish requires --run-id', ExitCode.BadConfig);
  const reason = await incompleteReason(a, d);
  const secrets = [env.AGENT_LLM_API_KEY ?? '', env.AGENT_SCREENING_API_KEY ?? ''].filter(Boolean);
  const itemErrors = [...(await stateItemErrors(a, d)), ...(await applyFailuresOf(a, d))].map((e) => redactAll(e, secrets));
  const counts = { items_failed: itemErrors.length, item_errors: itemErrors };
  let res = await mcp('finish_run', { run_id: runId, status: reason ? 'failed' : 'completed', stopped_reason: reason, ...counts });
  if (failed(res) && !reason) {
    // The server's coverage guard refused `completed`: report the shortfall honestly.
    await mcp('finish_run', { run_id: runId, status: 'failed', stopped_reason: `coverage incomplete: ${res.content}`.slice(0, MAX_STOPPED_REASON_CHARS), ...counts });
    return ExitCode.ProviderError;
  }
  return failed(res) ? ExitCode.ProviderError : ExitCode.Success;
}

function fail(d: Resolved, message: string, code: number): number {
  d.stderr(message);
  return code;
}

/**
 * Run one pipeline subcommand and return its exit code (never exits).
 *
 * @param argv Arguments after the script: `<command> [flags]`.
 * @param env Environment (same variables as cli.ts).
 * @param deps Injectable dependencies for tests.
 */
export async function runPipelineCli(argv: string[], env: NodeJS.ProcessEnv, deps: PipelineDeps = {}): Promise<number> {
  const d = withDefaults(deps);
  const a = parsePipelineArgs(argv);
  if (a.command === 'stage-prompt') return cmdStagePrompt(a, d);
  if (!['start', 'discover-screen', 'finish'].includes(a.command)) {
    return fail(d, `unknown command '${a.command}' (start|discover-screen|stage-prompt|finish)`, ExitCode.BadConfig);
  }
  let config: CliConfig | undefined;
  if (a.command === 'discover-screen') {
    const loaded = await loadConfig(a, env, d).catch((e: unknown) => String(e));
    if (typeof loaded === 'string') return fail(d, `configuration error: ${loaded}`, ExitCode.BadConfig);
    config = loaded;
    const tokens = tokensOf(config);
    const raw = d.stderr;
    d.stderr = (line) => raw(redactAll(line, tokens));
  }
  const pool = await connect(a, env, d);
  if (!pool) return fail(d, 'mcp connection failure: no tools available from any configured MCP server', ExitCode.McpFailure);
  try {
    if (a.command === 'start') return await cmdStart(a, mcpCaller(pool), d);
    if (a.command === 'finish') return await cmdFinish(a, mcpCaller(pool), d, env);
    return await cmdDiscoverScreen(a, env, pool, d, config!);
  } catch (err) {
    return fail(d, `${a.command} failed: ${err instanceof Error ? err.message : String(err)}`, ExitCode.ProviderError);
  }
}

// Runtime guard: run as a script but stay importable.
if (import.meta.url === `file://${process.argv[1]}`) {
  runPipelineCli(process.argv.slice(2), process.env)
    .then((code) => process.exit(code))
    .catch((err) => {
      const secrets = [process.env.AGENT_LLM_API_KEY ?? '', process.env.AGENT_SCREENING_API_KEY ?? ''];
      process.stderr.write(`fatal: ${redactAll(err instanceof Error ? err.message : String(err), secrets)}\n`);
      process.exit(1);
    });
}
