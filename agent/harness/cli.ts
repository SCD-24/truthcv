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
  /**
   * The model's context window in tokens, as stated by the operator, or 0 when
   * unstated. 0 means "unknown" and disables PROACTIVE compaction — never a
   * guess, because compacting against a wrong window fails both ways: too high
   * still overflows, too low silently discards context that was fitting. A run
   * without it is still covered reactively, when the provider says the context
   * is too long.
   */
  contextWindow: number;
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

/**
 * Parse `--context-window`/`AGENT_CONTEXT_WINDOW`; 0 when unset, NaN if invalid.
 *
 * There is deliberately no per-model table behind this. A table of model ids to
 * window sizes is wrong the day a model ships and wrong again when a provider
 * changes a served window, and being wrong here is worse than knowing nothing:
 * the reactive path already covers an unstated window using the provider's own
 * verdict. So the number is stated by whoever deployed the model, or not at all.
 *
 * State it as the model's INPUT capacity, not its headline total: the two
 * differ by whatever the provider reserves for the response (Anthropic reports
 * the input figure as `max_input_tokens` on its models endpoint), and the
 * difference is large enough to matter at the trigger point.
 */
function resolveContextWindow(flag: string | undefined, envVal: string | undefined): number {
  const raw = (flag || envVal || '').trim();
  if (!raw) return 0;
  // Digits only, deliberately. parseInt stops at the first non-digit and keeps
  // what it has, which turns every natural way an operator writes a large
  // number into a small one: "1e6" -> 1, "128k" -> 128, "1_000_000" -> 1,
  // "0x20000" -> 0. Each of those validates as a positive integer and then
  // compacts the conversation to its floor on every single turn, silently.
  if (!/^\d+$/.test(raw)) return Number.NaN;
  return Number.parseInt(raw, 10);
}

/**
 * Smallest window worth acting on.
 *
 * Below this the reserve alone exceeds the trigger, so every turn compacts and
 * the agent runs with no memory beyond the pinned instructions and the last
 * few messages — while looking healthy. A figure this small is an operator
 * typo, not an intent, so it is refused rather than honoured.
 */
const MIN_CONTEXT_WINDOW = 8192;

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
    contextWindow: resolveContextWindow(f['context-window'], env.AGENT_CONTEXT_WINDOW),
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
  if (!Number.isInteger(config.contextWindow) || config.contextWindow < 0)
    errors.push('--context-window must be a whole number of tokens, digits only (0 or unset means unknown)');
  else if (config.contextWindow > 0 && config.contextWindow < MIN_CONTEXT_WINDOW)
    errors.push(`--context-window must be at least ${MIN_CONTEXT_WINDOW} tokens, or 0/unset for unknown`);
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
      // Omitted entirely when unstated, so the loop's own "no window, no
      // proactive compaction" guard is the single place that decision lives.
      ...(config.contextWindow ? { compactionConfig: { contextWindow: config.contextWindow } } : {}),
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
 * Maximum characters of failed-tool `content` copied onto a `toolResult` line.
 *
 * A real error message from an MCP server is a sentence or a short stack, far
 * inside this bound; it exists only so a pathological one — a server echoing a
 * whole page back as its message — cannot turn a single failed call into a
 * megabyte of run log. 2000 characters is generous enough that no realistic
 * message is ever cut, and small enough that even a run failing every turn
 * stays a readable file.
 *
 * The bound is on UTF-16 code units — what `String.length` counts — and not on
 * bytes, which is what a log file is actually made of. The two differ by up to
 * a factor of three once the text is not Latin: 2000 CJK characters are 2000
 * code units but 6028 bytes of UTF-8. A capped line is therefore a few
 * kilobytes at worst, still small, and the cap is stated in the unit the code
 * can enforce rather than in one it cannot.
 */
const MAX_ERROR_CONTENT_CHARS = 2000;

/** Appended in place of the characters {@link errorContent} dropped. */
const TRUNCATION_MARKER = '…[truncated]';

/**
 * Emit one `toolResult` line per executed tool call.
 *
 * loop.ts exposes no per-tool-result callback, so these are DERIVED after the
 * run from `LoopResult.messages`: tool-call ids are correlated back to their
 * namespaced names to report which tool produced each result.
 *
 * Each line carries `toolCallId` because that correlation is otherwise lost to
 * a reader of the log: the whole batch is emitted AFTER the loop finishes, so
 * results do not sit next to the `toolCall` lines they answer, and a run that
 * calls the same tool ten times produces ten indistinguishable result lines.
 *
 * `content` is emitted ONLY when `isError` — deliberately, not by omission. A
 * successful browser tool result is a full page snapshot running to tens of
 * kilobytes, and logging those would bloat the log for no diagnostic gain: on
 * success the interesting fact is simply that the call succeeded.
 *
 * On failure what is logged is the ERROR TEXT ALONE, not the raw content: the
 * browser server attaches the generated Playwright source, the page metadata
 * and the accessibility snapshot to a failure as well as to a success, and
 * {@link errorSection} strips those because they carry the operator's personal
 * data and dwarf the message. The error text that remains is the ONE thing a
 * post-mortem needs, and its absence has already cost one investigation that
 * could not say why a run died.
 */
function emitToolResults(write: (obj: unknown) => void, messages: ConversationMessage[]): void {
  const names = toolCallNames(messages);
  for (const message of messages) {
    for (const result of message.toolResults ?? []) {
      const isError = Boolean(result.isError);
      const line = {
        type: 'toolResult',
        toolCallId: result.toolCallId,
        namespacedName: names.get(result.toolCallId) ?? 'unknown',
        isError,
      };
      write(isError ? { ...line, content: errorContent(result.content) } : line);
    }
  }
}

/**
 * Coerce a failed result's content into a bounded log string.
 *
 * This is a logging path that must never be able to fail a run, so anything
 * that is not a non-empty string — absent, empty, or a non-string a server
 * returned in spite of the declared type — becomes '' rather than throwing or
 * serialising to something a reader cannot parse.
 *
 * @param content The result content as received, of unknown runtime type.
 * @returns The message, truncated with {@link TRUNCATION_MARKER} if over the bound.
 */
function errorContent(content: unknown): string {
  if (typeof content !== 'string' || content.length === 0) return '';
  // Extract THEN truncate, never the reverse: the cap measures the text that is
  // actually logged. Truncating first would spend the whole budget on sections
  // about to be discarded — a long `Ran Playwright code` block sits between the
  // error and the end of the body, so a 2000-character prefix of the raw
  // content can be all personal data and no error message.
  return truncate(errorSection(content));
}

/**
 * Reduce a sectioned MCP response body to just its `### Error` section.
 *
 * The browser MCP server (`@playwright/mcp`) answers with a sequence of
 * `### <Name>` sections — `Error`, `Result`, `Ran Playwright code`, `Page`,
 * `Snapshot` — and attaches them to FAILED calls exactly as it does to
 * successful ones. `Ran Playwright code` is the generated source for the step
 * that was attempted, so a failed `browser_type` carries the literal value it
 * was typing: the operator's email, phone number, full name or salary, and a
 * failed `browser_navigate` carries any token in the URL's query string. The
 * server is started without `--secrets`, so its own masking has no keys and
 * masks nothing. Run logs sit on a persistent volume indefinitely, so the
 * error text is the only section that may be written to one.
 *
 * Content with NO `### ` header is returned UNCHANGED: errors from the app's
 * own MCP tools and from the harness's tool gate are plain sentences, and they
 * are the reason this content is logged at all.
 *
 * Sectioned content with no `Error` section yields '' — every other section is
 * one of the excluded ones, and the line still carries `isError`, the tool name
 * and the call id, which is what an unsectioned failure with an empty message
 * already logs.
 *
 * @param content The raw content string of a failed tool result.
 * @returns The error section's body, or the whole input when it has no sections.
 */
function errorSection(content: string): string {
  const sections = content.split(/^### /m);
  if (sections.length === 1) return content;
  for (const section of sections) {
    const newline = section.indexOf('\n');
    const name = newline === -1 ? section : section.slice(0, newline);
    if (name.trim() !== 'Error') continue;
    // Sections are blank-line separated upstream, so the body would otherwise
    // end in the separator that precedes the next header.
    return newline === -1 ? '' : section.slice(newline + 1).trimEnd();
  }
  return '';
}

/**
 * Cap `text` at {@link MAX_ERROR_CONTENT_CHARS}, marking that it was cut.
 *
 * Slicing at a fixed offset can land between the two halves of a surrogate
 * pair, leaving a lone high surrogate at the end. The line stays valid JSON —
 * `JSON.stringify` escapes it — but a consumer that parses it back gets an
 * ill-formed string ending in mojibake, so a trailing unpaired high surrogate
 * is dropped. `String.prototype.toWellFormed` would do this, but it is an
 * ES2024 library declaration and this package compiles against the ES2022 lib
 * (`agent/tsconfig.json`), so the check is written out instead.
 *
 * @param text The already-extracted error text.
 * @returns `text`, or a well-formed prefix of it plus {@link TRUNCATION_MARKER}.
 */
function truncate(text: string): string {
  if (text.length <= MAX_ERROR_CONTENT_CHARS) return text;
  const cut = text.slice(0, MAX_ERROR_CONTENT_CHARS);
  const last = cut.charCodeAt(cut.length - 1);
  const splitPair = last >= 0xd800 && last <= 0xdbff;
  return `${splitPair ? cut.slice(0, -1) : cut}${TRUNCATION_MARKER}`;
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
    // The same number the compaction trigger uses. Ollama needs it stated on
    // the request (`options.num_ctx`) because a local server otherwise serves
    // its own default; deriving both from one figure is what stops the harness
    // compacting against one window while the server enforces another.
    ...(config.contextWindow ? { contextWindow: config.contextWindow } : {}),
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
