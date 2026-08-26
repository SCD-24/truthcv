/**
 * Headless CLI entry point for the agent harness.
 *
 * `agent/daily-apply.sh` (a separate, later task) invokes this as
 * `node dist/harness/cli.js`, feeds it a prompt, and reads the child's EXIT
 * CODE to decide what happened. That exit-code contract is the machine
 * interface and is deliberately narrow and stable:
 *
 *   0  success        — the loop ended cleanly (`stopReason === 'end'`).
 *   2  turn cap       — the hard turn cap stopped the loop (`turnCapReached`).
 *   3  provider error — a non-retryable provider error, a truncated ('length')
 *                       or otherwise non-success loop outcome, or an unexpected
 *                       throw out of the loop.
 *   4  MCP failure    — the MCP layer could not be brought up at all: loading
 *                       the MCP config threw, pool construction threw, OR the
 *                       constructed pool exposes ZERO tools (every configured
 *                       server was unreachable, so the agent has no tool surface
 *                       to act through). Per-server failures that still leave
 *                       SOME tools available are intentionally NOT a 4 — the
 *                       pool isolates them and the run proceeds, matching the
 *                       pool's own isolation design.
 *   5  bad config     — a required input is missing or invalid (prompt, model,
 *                       provider, wire, max-turns, or the auth rule below),
 *                       detected BEFORE any provider adapter or MCP pool is
 *                       constructed.
 *   1  fatal          — reserved for a truly unexpected crash in the runtime
 *                       guard (should not happen; runCli catches its own paths).
 *
 * Auth rule: `ollama` may run with an empty token but MUST have a base URL;
 * every other provider MUST have a non-empty token.
 *
 * Progress is streamed to stdout as JSON Lines (one JSON object per line):
 * a `turnStart` per turn, the harness's own `text`/`toolCall`/`usage`/`error`
 * (and `reasoning`/`loopEvent`) events verbatim, a `toolResult` per executed
 * tool, and a final `done` carrying the outcome and exit code.
 *
 * SECURITY: the credential token is NEVER echoed. Every stdout and stderr write
 * passes through {@link redact}, which strips the raw token from the text as a
 * defense-in-depth guard even if an upstream error message happened to embed it.
 */

import { readFile, writeFile } from 'node:fs/promises';

import { createMcpClientPool, type McpClientPool } from './mcp/client.js';
import { loadMcpConfig, type McpServerConfig } from './mcp/config.js';
import {
  createProviderAdapter,
  type Provider,
  type ProviderAdapterOptions,
  type Wire,
} from './providers/registry.js';
import type { ConversationMessage, HarnessEvent, ProviderAdapter } from './providers/types.js';
import { runLoop, type LoopEvent, type LoopOutcome, type LoopResult } from './loop.js';

/** The CLI's process exit codes; see the module comment for the full contract. */
export const ExitCode = {
  /** The loop ended cleanly. */
  Success: 0,
  /** The hard turn cap stopped the loop. */
  TurnCapReached: 2,
  /** A non-retryable provider error or other non-success loop outcome. */
  ProviderError: 3,
  /** The MCP layer could not be brought up at all. */
  McpFailure: 4,
  /** A required input was missing or invalid, detected before startup. */
  BadConfig: 5,
} as const;

/** Default hard turn cap when neither flag nor env supplies one. */
const DEFAULT_MAX_TURNS = 40;

/**
 * The system prompt sent on every request. The user's prompt is delivered as
 * the initial user message; this CLI adds no separate system prompt of its own
 * (a later task may introduce one).
 */
const SYSTEM_PROMPT = '';

/** Parsed argv split into `--flag value` pairs and bare positional arguments. */
export interface ParsedArgs {
  /** Flag name (without the leading `--`) to its string value ('' if valueless). */
  flags: Record<string, string>;
  /** Positional arguments in order. */
  positional: string[];
}

/** The fully-resolved configuration a single run needs. */
export interface CliConfig {
  /** The task prompt delivered as the initial user message. */
  prompt: string;
  /** Model identifier requested from the provider. */
  model: string;
  /** Logical provider being targeted. */
  provider: Provider;
  /** Wire protocol the provider speaks. */
  wire: Wire;
  /** Credential token; may be empty only for `ollama`. */
  token: string;
  /** Base URL; required for `ollama`, optional otherwise. */
  baseUrl: string;
  /**
   * How `token` should be presented on the wire — `'oauth'` (Bearer token),
   * `'api_key'` (vendor api-key header), or `'url'` (no credential, e.g.
   * ollama). Distinct from `provider`: a claude connection can be either
   * oauth or api_key. Undefined defaults to `'api_key'` in the adapter
   * registry, so this MUST be threaded through explicitly for oauth claude
   * connections or their token is sent via the wrong header and rejected.
   */
  authType?: 'oauth' | 'api_key' | 'url';
  /** Path to the MCP config JSON file. */
  mcpConfigPath: string;
  /** Hard cap on completed loop turns. */
  maxTurns: number;
  /** Where to write the final assistant message text; omitted to write nothing. */
  outputFile?: string;
}

/**
 * Injectable dependencies for {@link runCli}. Every field defaults to the real
 * implementation; tests supply fakes so no network or real MCP server is
 * touched.
 */
export interface CliDeps {
  /** Build the provider adapter. Defaults to {@link createProviderAdapter}. */
  createAdapter?: (opts: ProviderAdapterOptions) => ProviderAdapter;
  /** Build and connect the MCP pool. Defaults to {@link createMcpClientPool}. */
  createPool?: (servers: McpServerConfig[]) => Promise<McpClientPool>;
  /** Load the MCP server list. Defaults to {@link loadMcpConfig}. */
  loadConfig?: (path: string, env: NodeJS.ProcessEnv) => McpServerConfig[];
  /** Write one stdout line. Defaults to `process.stdout`. */
  stdout?: (line: string) => void;
  /** Write one stderr line. Defaults to `process.stderr`. */
  stderr?: (line: string) => void;
  /** Read a UTF-8 text file. Defaults to `node:fs/promises` readFile. */
  readFileText?: (path: string) => Promise<string>;
  /** Read the full prompt from stdin. Defaults to draining `process.stdin`. */
  readStdin?: () => Promise<string>;
  /** Write the final assistant text to a file. Defaults to `writeFile`. */
  writeOutput?: (path: string, text: string) => Promise<void>;
}

/** The same dependency set with every field resolved to a concrete function. */
interface ResolvedDeps {
  createAdapter: (opts: ProviderAdapterOptions) => ProviderAdapter;
  createPool: (servers: McpServerConfig[]) => Promise<McpClientPool>;
  loadConfig: (path: string, env: NodeJS.ProcessEnv) => McpServerConfig[];
  stdout: (line: string) => void;
  stderr: (line: string) => void;
  readFileText: (path: string) => Promise<string>;
  readStdin: () => Promise<string>;
  writeOutput: (path: string, text: string) => Promise<void>;
}

/** The redacting stdout (JSON) and stderr (text) writers for a run. */
interface Emitter {
  /** Serialize an object to a redacted JSON line on stdout. */
  json: (obj: unknown) => void;
  /** Write a redacted text line on stderr. */
  err: (text: string) => void;
}

/**
 * Split argv into `--flag [value]` pairs and positional arguments.
 *
 * A `--flag` consumes the next token as its value unless that token is itself a
 * `--flag` (or absent), in which case the flag is recorded with an empty value.
 *
 * @param argv Arguments after the node binary and script (e.g. `process.argv.slice(2)`).
 * @returns The parsed flags and positionals.
 */
export function parseArgs(argv: string[]): ParsedArgs {
  const flags: Record<string, string> = {};
  const positional: string[] = [];
  for (let i = 0; i < argv.length; i += 1) {
    const arg = argv[i];
    if (!arg.startsWith('--')) {
      positional.push(arg);
      continue;
    }
    const hasNext = i + 1 < argv.length;
    const next = hasNext ? argv[i + 1] : '';
    const hasValue = hasNext && !next.startsWith('--');
    flags[arg.slice(2)] = hasValue ? next : '';
    if (hasValue) i += 1;
  }
  return { flags, positional };
}

/** Read the prompt from `--prompt-file`, else a positional, else stdin. */
async function resolvePrompt(
  parsed: ParsedArgs,
  io: { readFileText: (p: string) => Promise<string>; readStdin: () => Promise<string> },
): Promise<string> {
  const file = parsed.flags['prompt-file'];
  if (file) return (await io.readFileText(file)).trim();
  if (parsed.positional.length > 0) return parsed.positional[parsed.positional.length - 1];
  return (await io.readStdin()).trim();
}

/** Parse `--max-turns`/`AGENT_MAX_TURNS`, defaulting when unset; NaN if invalid. */
function resolveMaxTurns(flag: string | undefined, envVal: string | undefined): number {
  const raw = flag || envVal;
  if (!raw) return DEFAULT_MAX_TURNS;
  return Number.parseInt(raw, 10);
}

/**
 * Merge flags, environment and defaults (and read the prompt) into a
 * {@link CliConfig}. Performs no validation and constructs nothing.
 *
 * @param parsed The parsed argv.
 * @param env The environment providing fallbacks.
 * @param io The prompt-source functions (file/stdin), injectable for tests.
 * @returns The resolved, not-yet-validated configuration.
 */
export async function resolveConfig(
  parsed: ParsedArgs,
  env: NodeJS.ProcessEnv,
  io: { readFileText: (p: string) => Promise<string>; readStdin: () => Promise<string> },
): Promise<CliConfig> {
  const f = parsed.flags;
  const prompt = await resolvePrompt(parsed, io);
  return {
    prompt,
    model: f.model ?? env.AGENT_LLM_MODEL ?? '',
    provider: (f.provider ?? env.AGENT_LLM_PROVIDER ?? '') as Provider,
    wire: (f.wire ?? env.AGENT_LLM_WIRE ?? '') as Wire,
    token: tokenFrom(f, env),
    baseUrl: f['base-url'] ?? env.AGENT_LLM_BASE_URL ?? '',
    authType: (f['auth-type'] ?? env.AGENT_LLM_AUTH_TYPE ?? undefined) as CliConfig['authType'],
    mcpConfigPath: f['mcp-config'] ?? env.MCP_CONFIG_PATH ?? 'mcp.json',
    maxTurns: resolveMaxTurns(f['max-turns'], env.AGENT_MAX_TURNS),
    outputFile: f['output-file'] || undefined,
  };
}

/** Known providers, used to validate the resolved provider string. */
const PROVIDERS: readonly Provider[] = ['claude', 'codex', 'openrouter', 'ollama'];
/** Known wire protocols, used to validate the resolved wire string. */
const WIRES: readonly Wire[] = ['anthropic-messages', 'openai-chat-completions'];

/** Whether the auth rule (token, or base-url for ollama) is satisfied. */
function validateAuth(config: CliConfig): string[] {
  if (config.provider === 'ollama') {
    return config.baseUrl ? [] : ['ollama requires a --base-url (or AGENT_LLM_BASE_URL)'];
  }
  return config.token ? [] : ['a non-empty --token (or AGENT_LLM_API_KEY) is required for this provider'];
}

/**
 * Validate a resolved configuration, returning a list of human-readable
 * problems (empty when the config is usable). Messages NEVER include the token
 * value.
 *
 * @param config The resolved configuration.
 * @returns Zero or more error strings; a non-empty result means exit code 5.
 */
export function validateConfig(config: CliConfig): string[] {
  const errors: string[] = [];
  if (!config.prompt) errors.push('a prompt is required (--prompt-file, stdin, or a positional argument)');
  if (!config.model) errors.push('a model is required (--model or AGENT_LLM_MODEL)');
  if (!PROVIDERS.includes(config.provider)) errors.push('a valid --provider (claude|codex|openrouter|ollama) is required');
  if (!WIRES.includes(config.wire)) errors.push('a valid --wire (anthropic-messages|openai-chat-completions) is required');
  if (!Number.isInteger(config.maxTurns) || config.maxTurns <= 0) errors.push('--max-turns must be a positive integer');
  errors.push(...validateAuth(config));
  return errors;
}

/**
 * Remove every occurrence of the raw token from `text`, replacing it with a
 * placeholder. A no-op when the token is empty (so a valueless ollama token
 * cannot turn into a wildcard replacement).
 *
 * @param text The text about to be written.
 * @param token The credential token to strip.
 * @returns The text with the token redacted.
 */
export function redact(text: string, token: string): string {
  if (!token) return text;
  return text.split(token).join('<redacted>');
}

/**
 * Return the final assistant message's text: the content of the last
 * `assistant`-role message, or '' if there is none.
 *
 * @param messages The conversation history from a {@link LoopResult}.
 * @returns The final assistant text.
 */
export function finalAssistantText(messages: ConversationMessage[]): string {
  for (let i = messages.length - 1; i >= 0; i -= 1) {
    if (messages[i].role === 'assistant') return messages[i].content;
  }
  return '';
}

/**
 * Run the CLI once and return its exit code (never calls `process.exit`, so it
 * is directly testable). All output goes through the injectable, redacting
 * writers in `deps`.
 *
 * @param argv Arguments after the node binary and script.
 * @param env The environment providing fallbacks.
 * @param deps Injectable dependencies; defaults are the real implementations.
 * @returns The process exit code (see {@link ExitCode}).
 */
export async function runCli(argv: string[], env: NodeJS.ProcessEnv, deps: CliDeps = {}): Promise<number> {
  const d = withDefaults(deps);
  const parsed = parseArgs(argv);
  const token = tokenFrom(parsed.flags, env);
  const emit: Emitter = {
    json: (obj) => d.stdout(redact(JSON.stringify(obj), token)),
    err: (text) => d.stderr(redact(text, token)),
  };
  let config: CliConfig;
  try {
    config = await resolveConfig(parsed, env, d);
  } catch (err) {
    emit.err(`configuration error: ${errorMessage(err)}`);
    return ExitCode.BadConfig;
  }
  const errors = validateConfig(config);
  if (errors.length > 0) {
    emit.err(`configuration error: ${errors.join('; ')}`);
    return ExitCode.BadConfig;
  }
  return runOnce(config, env, d, emit);
}

/** Build pool and adapter, run the loop, and report; returns the exit code. */
async function runOnce(config: CliConfig, env: NodeJS.ProcessEnv, d: ResolvedDeps, emit: Emitter): Promise<number> {
  const pool = await tryBuildPool(config, env, d, emit);
  if (typeof pool === 'number') return pool;
  const adapter = d.createAdapter(adapterOptions(config));
  const outcome = await runAgent(adapter, pool, config, emit);
  if (typeof outcome === 'number') return outcome;
  return report(outcome, config, d, emit);
}

/** Build and connect the MCP pool, or return an exit code on total failure. */
async function tryBuildPool(
  config: CliConfig,
  env: NodeJS.ProcessEnv,
  d: ResolvedDeps,
  emit: Emitter,
): Promise<McpClientPool | number> {
  try {
    const servers = d.loadConfig(config.mcpConfigPath, env);
    const pool = await d.createPool(servers);
    if (pool.listTools().length === 0) {
      emit.err('mcp connection failure: no tools available from any configured MCP server');
      return ExitCode.McpFailure;
    }
    return pool;
  } catch (err) {
    emit.err(`mcp connection failure: ${errorMessage(err)}`);
    return ExitCode.McpFailure;
  }
}

/** Run the loop, streaming events; returns the result or an error exit code. */
async function runAgent(
  adapter: ProviderAdapter,
  pool: McpClientPool,
  config: CliConfig,
  emit: Emitter,
): Promise<LoopResult | number> {
  try {
    return await runLoop({
      adapter,
      pool,
      systemPrompt: SYSTEM_PROMPT,
      initialMessages: [{ role: 'user', content: config.prompt }],
      config: { maxTurns: config.maxTurns },
      onEvent: createEventStream(emit.json),
    });
  } catch (err) {
    emit.err(`provider error: ${errorMessage(err)}`);
    return ExitCode.ProviderError;
  }
}

/** Emit derived tool results and the final `done`, write output, return the code. */
async function report(result: LoopResult, config: CliConfig, d: ResolvedDeps, emit: Emitter): Promise<number> {
  const exitCode = exitCodeFor(result.stopReason);
  emitToolResults(emit.json, result.messages);
  emit.json({ type: 'done', stopReason: result.stopReason, turns: result.turns, exitCode });
  if (config.outputFile) await d.writeOutput(config.outputFile, finalAssistantText(result.messages));
  return exitCode;
}

/**
 * Build the loop `onEvent` handler that streams JSON-line events.
 *
 * It synthesises a `turnStart` at the start of each turn (loop.ts emits no such
 * event, so it is derived here from the event stream), passes the harness's own
 * events through verbatim, and SUPPRESSES the per-turn `done` events — a single
 * final `done` carrying the outcome is emitted by {@link report} instead.
 */
function createEventStream(write: (obj: unknown) => void): (event: HarnessEvent | LoopEvent) => void {
  let turn = 0;
  let open = false;
  const ensureTurn = (): void => {
    if (open) return;
    turn += 1;
    open = true;
    write({ type: 'turnStart', turn });
  };
  return (event) => {
    if (event.type === 'done') {
      ensureTurn();
      open = false;
      return;
    }
    if (event.type === 'loopEvent') {
      write(event);
      return;
    }
    ensureTurn();
    write(event);
  };
}

/**
 * Emit one `toolResult` line per executed tool call.
 *
 * loop.ts exposes no per-tool-result callback, so these are DERIVED after the
 * run from `LoopResult.messages`: tool-call ids are correlated back to their
 * namespaced names to report which tool produced each result.
 */
function emitToolResults(write: (obj: unknown) => void, messages: ConversationMessage[]): void {
  const names = toolCallNames(messages);
  for (const message of messages) {
    for (const result of message.toolResults ?? []) {
      write({ type: 'toolResult', namespacedName: names.get(result.toolCallId) ?? 'unknown', isError: Boolean(result.isError) });
    }
  }
}

/** Map every tool-call id in the conversation to its namespaced tool name. */
function toolCallNames(messages: ConversationMessage[]): Map<string, string> {
  const map = new Map<string, string>();
  for (const message of messages) {
    for (const call of message.toolCalls ?? []) map.set(call.id, call.name);
  }
  return map;
}

/** Map a loop outcome to its process exit code. */
function exitCodeFor(stopReason: LoopOutcome): number {
  if (stopReason === 'end') return ExitCode.Success;
  if (stopReason === 'turnCapReached') return ExitCode.TurnCapReached;
  return ExitCode.ProviderError;
}

/** Project a {@link CliConfig} onto the provider adapter's option shape. */
function adapterOptions(config: CliConfig): ProviderAdapterOptions {
  return {
    provider: config.provider,
    wire: config.wire,
    model: config.model,
    token: config.token,
    baseUrl: config.baseUrl,
    authType: config.authType,
  };
}

/** Resolve the token from `--token`/`AGENT_LLM_API_KEY` (used for redaction too). */
function tokenFrom(flags: Record<string, string>, env: NodeJS.ProcessEnv): string {
  return flags.token ?? env.AGENT_LLM_API_KEY ?? '';
}

/** Fill in every unset dependency with its real default implementation. */
function withDefaults(deps: CliDeps): ResolvedDeps {
  return {
    createAdapter: deps.createAdapter ?? createProviderAdapter,
    createPool: deps.createPool ?? ((servers) => createMcpClientPool(servers)),
    loadConfig: deps.loadConfig ?? loadMcpConfig,
    stdout: deps.stdout ?? ((line) => void process.stdout.write(`${line}\n`)),
    stderr: deps.stderr ?? ((line) => void process.stderr.write(`${line}\n`)),
    readFileText: deps.readFileText ?? ((path) => readFile(path, 'utf8')),
    readStdin: deps.readStdin ?? defaultReadStdin,
    writeOutput: deps.writeOutput ?? ((path, text) => writeFile(path, text, 'utf8')),
  };
}

/** Drain stdin to a single UTF-8 string. */
async function defaultReadStdin(): Promise<string> {
  const chunks: Buffer[] = [];
  for await (const chunk of process.stdin) chunks.push(chunk as Buffer);
  return Buffer.concat(chunks).toString('utf8');
}

/** Coerce an unknown thrown value into a message string. */
function errorMessage(err: unknown): string {
  return err instanceof Error ? err.message : String(err);
}

/**
 * Resolve argv/env and run the CLI once, returning the exit code. Kept separate
 * from the runtime guard so tests can import and drive it directly.
 *
 * @param argv Arguments after the node binary and script.
 * @param env The environment providing fallbacks.
 * @returns The process exit code.
 */
export async function main(
  argv: string[] = process.argv.slice(2),
  env: NodeJS.ProcessEnv = process.env,
): Promise<number> {
  return runCli(argv, env);
}

// Runtime guard: run as a script (`node dist/harness/cli.js`) but stay importable.
if (import.meta.url === `file://${process.argv[1]}`) {
  main()
    .then((code) => process.exit(code))
    .catch((err) => {
      const raw = err instanceof Error ? err.message : String(err);
      process.stderr.write(`fatal: ${redact(raw, process.env.AGENT_LLM_API_KEY ?? '')}\n`);
      process.exit(1);
    });
}
