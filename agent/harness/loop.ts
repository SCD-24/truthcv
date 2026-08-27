/**
 * The provider-agnostic agent loop.
 *
 * This drives an unattended, overnight job-application agent that acts under a
 * real person's identity. That is precisely why the loop is built around a
 * HARD, caller-supplied turn cap and disciplined failure handling rather than a
 * "run until the model says stop" design: an unbounded loop, or a tool call
 * recovered from a truncated (and therefore possibly nonsensical) model
 * response executed for real, is a genuine operational hazard here, not a
 * theoretical one. Every provider and every MCP dependency is injected, so the
 * whole loop is exercisable with fakes and never has to touch a network.
 */

import type {
  ConversationMessage,
  HarnessEvent,
  ModelRequest,
  ProviderAdapter,
  StopReason,
  ToolCall,
  ToolResult,
} from './providers/types.js';
import type { McpClientPool } from './mcp/client.js';
import { buildToolRegistry, executeToolCall, type RegisteredTool } from './tools.js';
import { compact, shouldCompact, type CompactionConfig } from './compaction.js';

/** An error event narrowed out of the {@link HarnessEvent} union. */
type ErrorEvent = Extract<HarnessEvent, { type: 'error' }>;

/** A terminal `done` event narrowed out of the {@link HarnessEvent} union. */
type DoneEvent = Extract<HarnessEvent, { type: 'done' }>;

/** Default cap on consecutive malformed-tool-call reflection retries. */
const DEFAULT_MAX_REFLECTIONS = 3;

/** Default ceiling on a single retry backoff, so a "retry in hours" fails fast. */
const DEFAULT_MAX_RETRY_DELAY_MS = 60_000;

/**
 * Default cap on consecutive retryable-error retries within one turn. Capping
 * the DELAY alone is not enough: a provider that keeps returning a retryable
 * error (e.g. a sustained rate limit) would otherwise retry forever without
 * ever advancing a turn or a reflection, defeating the loop's own turn cap.
 */
const DEFAULT_MAX_RETRIES = 8;

/** Base unit for exponential backoff and its jitter, in milliseconds. */
const BASE_RETRY_DELAY_MS = 1_000;

/**
 * Default number of turns reserved at the end of the budget for the model to
 * wind up in.
 *
 * Without this the loop simply stops mid-action: the run's last observed
 * behaviour was a half-filled application form, abandoned with no account of
 * what was left undone. Two turns is enough to abandon cleanly and make the
 * closing tool calls, and cheap against any realistic cap.
 */
const DEFAULT_WRAP_UP_TURNS = 2;

/**
 * What the model is told when it enters the wrap-up window.
 *
 * Deliberately names no specific tool: this loop is provider- and
 * application-neutral, and the run's own prompt is what tells it which call
 * records a stopped run.
 */
const WRAP_UP_MESSAGE =
  'You are close to this run\'s turn limit and will be stopped shortly. Do NOT begin any new ' +
  'work, and do not start or continue filling in a form you cannot finish in the next turn or ' +
  'two. Abandon anything half-done, then make your closing tool calls now: record where you ' +
  'stopped and what you left unfinished, honestly, so the next run can pick it up.';

/**
 * Loop tuning. `maxTurns` is REQUIRED and is the hard cap: there is deliberately
 * no unbounded default, because this loop runs unattended overnight and must
 * stop on its own.
 */
export interface LoopConfig {
  /** Hard cap on completed turns. Required; no default — the loop must be bounded. */
  maxTurns: number;
  /** Cap on consecutive malformed-tool-call reflection retries. Defaults to 3. */
  maxConsecutiveReflections?: number;
  /** Ceiling on any single retry backoff delay, in ms. Defaults to 60000. */
  maxRetryDelayMs?: number;
  /** Cap on consecutive retryable-error retries within one turn. Defaults to 8. */
  maxConsecutiveRetries?: number;
  /**
   * Turns reserved at the end of `maxTurns` for the model to wind up in.
   * Defaults to 2. Zero disables the warning entirely — the loop then stops
   * mid-action as it did before.
   */
  wrapUpTurns?: number;
}

/**
 * The classes an {@link ErrorEvent} is bucketed into. The first three are the
 * retryable buckets; the rest are fatal and short-circuit the loop.
 */
export type ErrorClass =
  | 'authentication'
  | 'bad-request'
  | 'context-window-exceeded'
  | 'usage-limit'
  | 'rate-limit'
  | 'timeout'
  | 'service-unavailable'
  | 'unknown';

/**
 * The loop's own outcome. It widens the shared {@link StopReason} with
 * `turnCapReached`, the distinct result meaning the hard turn cap stopped the
 * loop while the model still wanted to keep going.
 */
export type LoopOutcome = StopReason | 'turnCapReached';

/** A loop-level progress event, distinct from a provider {@link HarnessEvent}. */
export interface LoopEvent {
  /** Discriminant marking this as a loop event to an `onEvent` consumer. */
  type: 'loopEvent';
  /** What happened. */
  kind: 'compaction' | 'retry' | 'reflection' | 'turnCapReached' | 'wrapUp' | 'stop';
  /** The turn number this event relates to, when applicable. */
  turn?: number;
  /** Human-readable detail for a log line. */
  detail?: string;
}

/** Everything {@link runLoop} needs, all injectable for testing. */
export interface RunLoopOptions {
  /** The provider adapter to call each turn. */
  adapter: ProviderAdapter;
  /** The MCP client pool tool calls dispatch through. */
  pool: McpClientPool;
  /** The system prompt sent on every request. */
  systemPrompt: string;
  /** The starting conversation history. */
  initialMessages: ConversationMessage[];
  /** Loop tuning, including the required hard turn cap. */
  config: LoopConfig;
  /** Optional compaction tuning; compaction runs only with a real contextWindow. */
  compactionConfig?: CompactionConfig;
  /** Optional per-event hook so a CLI can stream progress. Never required. */
  onEvent?: (event: HarnessEvent | LoopEvent) => void;
  /** Injectable sleep so tests need not wait on real timers. Defaults to setTimeout. */
  sleep?: (ms: number) => Promise<void>;
}

/** The loop's final result. */
export interface LoopResult {
  /** Why the loop stopped, possibly the loop-specific `turnCapReached`. */
  stopReason: LoopOutcome;
  /** The full conversation history at termination. */
  messages: ConversationMessage[];
  /** How many turns completed. */
  turns: number;
}

/** Mutable state threaded through the loop's helpers. */
interface LoopState {
  messages: ConversationMessage[];
  turns: number;
  reflections: number;
  retries: number;
  /** Whether the wrap-up instruction has already been delivered, so entering
   * the window repeatedly cannot append it on every remaining turn. */
  wrapUpSent: boolean;
}

/** Per-iteration context handed to the outcome handlers. */
interface LoopContext {
  pool: McpClientPool;
  registry: RegisteredTool[];
  config: LoopConfig;
  onEvent?: (event: HarnessEvent | LoopEvent) => void;
  sleep: (ms: number) => Promise<void>;
}

/** The outcome of consuming one adapter response to its terminal event. */
type TurnOutcome = { kind: 'done'; done: DoneEvent } | { kind: 'error'; error: ErrorEvent };

/**
 * Classify an error event into an {@link ErrorClass}.
 *
 * A retryable event is one of the retryable buckets (defaulting to
 * `service-unavailable`); a non-retryable one is a fatal bucket (defaulting to
 * `bad-request`). The message string only narrows within the retryability the
 * adapter already declared.
 */
export function classifyError(event: ErrorEvent): ErrorClass {
  const msg = event.message.toLowerCase();
  return event.retryable ? classifyRetryable(msg) : classifyFatal(msg);
}

/** Narrow a retryable error message to its bucket. */
function classifyRetryable(msg: string): ErrorClass {
  if (msg.includes('rate limit') || msg.includes('429')) return 'rate-limit';
  if (msg.includes('timeout')) return 'timeout';
  return 'service-unavailable';
}

/** Narrow a non-retryable error message to its bucket. */
function classifyFatal(msg: string): ErrorClass {
  if (msg.includes('auth') || msg.includes('401') || msg.includes('403')) return 'authentication';
  if (msg.includes('context') || msg.includes('too many tokens')) return 'context-window-exceeded';
  if (msg.includes('usage limit') || msg.includes('quota')) return 'usage-limit';
  return 'bad-request';
}

/** Whether an {@link ErrorClass} is worth retrying with backoff. */
export function isRetryable(cls: ErrorClass): boolean {
  return cls === 'rate-limit' || cls === 'timeout' || cls === 'service-unavailable';
}

/**
 * Exponential backoff with jitter, capped at `maxRetryDelayMs`.
 *
 * The cap matters: a provider effectively saying "retry in four hours" must
 * fail fast against the cap instead of parking the run for hours.
 */
export function backoffDelay(attempt: number, maxRetryDelayMs: number): number {
  const base = BASE_RETRY_DELAY_MS * 2 ** attempt;
  const jitter = Math.random() * BASE_RETRY_DELAY_MS;
  return Math.min(base + jitter, maxRetryDelayMs);
}

/**
 * Run the agent loop to termination.
 *
 * Each turn re-reads the live MCP tool list (so a reconnected server becomes
 * usable mid-run), optionally compacts, sends one request, and dispatches on
 * the terminal event. Returns the final {@link LoopResult}; never loops without
 * a bound.
 */
export async function runLoop(opts: RunLoopOptions): Promise<LoopResult> {
  const { adapter, pool, systemPrompt, initialMessages, config, compactionConfig, onEvent } = opts;
  const sleep = opts.sleep ?? defaultSleep;
  const state: LoopState = { messages: [...initialMessages], turns: 0, reflections: 0, retries: 0, wrapUpSent: false };
  while (true) {
    const registry = await refreshRegistry(pool);
    state.messages = maybeCompact(state.messages, compactionConfig, onEvent);
    const tools = registry.map((r) => r.definition);
    const request: ModelRequest = { systemPrompt, messages: state.messages, tools };
    const outcome = await runOneTurn(adapter, request, onEvent);
    const result = await applyOutcome(outcome, state, { pool, registry, config, onEvent, sleep });
    if (result) return result;
  }
}

/** Refresh the live tool list and build a fresh registry for this turn. */
async function refreshRegistry(pool: McpClientPool): Promise<RegisteredTool[]> {
  await pool.refreshTools();
  return buildToolRegistry(pool.listTools());
}

/** Apply compaction before sending, but only when a real context window is set. */
function maybeCompact(
  messages: ConversationMessage[],
  config: CompactionConfig | undefined,
  onEvent?: (event: HarnessEvent | LoopEvent) => void,
): ConversationMessage[] {
  if (!config || !config.contextWindow) return messages;
  if (!shouldCompact(messages, undefined, config)) return messages;
  const { messages: compacted, record } = compact(messages, config);
  if (record) onEvent?.(loopEvent('compaction', undefined, record.summary));
  return compacted;
}

/** Consume one adapter response, forwarding events, to its terminal event. */
async function runOneTurn(
  adapter: ProviderAdapter,
  request: ModelRequest,
  onEvent?: (event: HarnessEvent | LoopEvent) => void,
): Promise<TurnOutcome> {
  let terminal: TurnOutcome | undefined;
  for await (const event of adapter.sendMessage(request)) {
    onEvent?.(event);
    if (event.type === 'done') terminal = { kind: 'done', done: event };
    else if (event.type === 'error') terminal = { kind: 'error', error: event };
  }
  if (terminal) return terminal;
  return { kind: 'error', error: { type: 'error', message: 'Adapter ended without a terminal event', retryable: false } };
}

/** Dispatch a terminal outcome; a returned result ends the loop. */
async function applyOutcome(
  outcome: TurnOutcome,
  state: LoopState,
  ctx: LoopContext,
): Promise<LoopResult | undefined> {
  if (outcome.kind === 'error') return applyError(outcome.error, state, ctx);
  return applyDone(outcome.done, state, ctx);
}

/**
 * Handle an error event: reflect on a malformed tool call, back off and retry a
 * retryable error, or short-circuit a fatal one.
 */
async function applyError(error: ErrorEvent, state: LoopState, ctx: LoopContext): Promise<LoopResult | undefined> {
  if (isMalformedToolCall(error)) return reflect(error, state, ctx);
  const cls = classifyError(error);
  if (!isRetryable(cls)) return finish('error', state, ctx, `non-retryable error: ${cls}`);
  const maxRetries = ctx.config.maxConsecutiveRetries ?? DEFAULT_MAX_RETRIES;
  if (state.retries >= maxRetries) return finish('error', state, ctx, 'retry limit exceeded');
  await backoff(state, ctx, error);
  return undefined;
}

/**
 * Feed a malformed-tool-call error back as a user turn and retry, bounded by
 * `maxConsecutiveReflections` so the loop cannot spin forever on a confused
 * model.
 */
function reflect(error: ErrorEvent, state: LoopState, ctx: LoopContext): LoopResult | undefined {
  state.reflections += 1;
  const max = ctx.config.maxConsecutiveReflections ?? DEFAULT_MAX_REFLECTIONS;
  if (state.reflections > max) return finish('error', state, ctx, 'reflection limit exceeded');
  state.messages.push({ role: 'user', content: reflectionMessage(error) });
  ctx.onEvent?.(loopEvent('reflection', state.turns, error.message));
  return undefined;
}

/**
 * Wait out a capped backoff for a retryable error; the turn is not advanced.
 *
 * A provider that sent `Retry-After` knows when its own limit resets and we do
 * not, so its number wins over the computed curve — still clamped by
 * `maxRetryDelayMs`, because a header asking for four hours must not park an
 * unattended run for four hours.
 */
async function backoff(state: LoopState, ctx: LoopContext, error: ErrorEvent): Promise<void> {
  const cap = ctx.config.maxRetryDelayMs ?? DEFAULT_MAX_RETRY_DELAY_MS;
  const asked = error.retryAfterMs;
  const delay = asked === undefined ? backoffDelay(state.retries, cap) : Math.min(asked, cap);
  const source = asked === undefined ? '' : ' (provider Retry-After)';
  state.retries += 1;
  ctx.onEvent?.(loopEvent('retry', state.turns, `retrying after ${Math.round(delay)}ms${source}`));
  await ctx.sleep(delay);
}

/** Handle a `done` event by advancing the turn and dispatching its stop reason. */
async function applyDone(done: DoneEvent, state: LoopState, ctx: LoopContext): Promise<LoopResult | undefined> {
  state.retries = 0;
  state.reflections = 0;
  state.turns += 1;
  state.messages.push(done.message);
  return dispatchStopReason(done, state, ctx);
}

/** Route a `done` event to the handler for its stop reason. */
async function dispatchStopReason(done: DoneEvent, state: LoopState, ctx: LoopContext): Promise<LoopResult | undefined> {
  switch (done.stopReason) {
    case 'end':
      return finish('end', state, ctx, 'model ended the turn');
    case 'toolCalls':
      return continueWithTools(done, state, ctx);
    case 'length':
      return handleLength(done, state, ctx);
    default:
      return finish(done.stopReason, state, ctx, `stop reason: ${done.stopReason}`);
  }
}

/** Execute every tool call this turn requested, then continue or hit the cap. */
async function continueWithTools(done: DoneEvent, state: LoopState, ctx: LoopContext): Promise<LoopResult | undefined> {
  const calls = done.message.toolCalls ?? [];
  const results = await executeTurnToolCalls(ctx.pool, calls, ctx.registry);
  state.messages.push(toolResultsMessage(results));
  return capOrContinue(state, ctx);
}

/**
 * Handle a TRUNCATED response. Tool calls recovered from a `length` stop are
 * never executed — their arguments may be incomplete and unsafe — so each is
 * failed with an error result and fed back. With no tool calls this is just a
 * truncated answer and the loop stops.
 */
async function handleLength(done: DoneEvent, state: LoopState, ctx: LoopContext): Promise<LoopResult | undefined> {
  const calls = done.message.toolCalls ?? [];
  if (calls.length === 0) return finish('length', state, ctx, 'truncated response, no tool calls');
  const results = calls.map(failTruncated);
  state.messages.push(toolResultsMessage(results));
  ctx.onEvent?.(loopEvent('stop', state.turns, 'truncated tool calls failed without execution'));
  return capOrContinue(state, ctx);
}

/** Stop with `turnCapReached` if the hard cap is now met, else continue —
 * warning the model once when it enters the wrap-up window. */
function capOrContinue(state: LoopState, ctx: LoopContext): LoopResult | undefined {
  if (state.turns >= ctx.config.maxTurns) {
    ctx.onEvent?.(loopEvent('turnCapReached', state.turns, `hard turn cap of ${ctx.config.maxTurns} reached`));
    return { stopReason: 'turnCapReached', messages: state.messages, turns: state.turns };
  }
  maybeWarnWrapUp(state, ctx);
  return undefined;
}

/**
 * Tell the model once that it is nearly out of turns.
 *
 * Delivered as its own user message rather than as text on the tool-results
 * message: the Anthropic Messages API requires a `tool_use` to be answered by
 * `tool_result` blocks immediately after, so text sharing that message ahead of
 * them is a 400. A separate following message is accepted.
 *
 * The warning does not extend the budget — `maxTurns` still stops the loop. It
 * only buys the model notice, so its last turns are a deliberate wind-down
 * instead of an arbitrary cut.
 */
function maybeWarnWrapUp(state: LoopState, ctx: LoopContext): void {
  const reserved = ctx.config.wrapUpTurns ?? DEFAULT_WRAP_UP_TURNS;
  // A reserve at or beyond the whole budget would fire on turn one and make
  // every run a wind-down; a zero reserve disables the warning by request.
  if (reserved <= 0 || reserved >= ctx.config.maxTurns) return;
  if (state.wrapUpSent) return;
  if (state.turns < ctx.config.maxTurns - reserved) return;
  state.wrapUpSent = true;
  state.messages.push({ role: 'user', content: WRAP_UP_MESSAGE });
  ctx.onEvent?.(
    loopEvent('wrapUp', state.turns, `${ctx.config.maxTurns - state.turns} turn(s) left — told the model to wind up`),
  );
}

/** Execute each allowed tool call in order through the choke point. */
async function executeTurnToolCalls(
  pool: McpClientPool,
  calls: ToolCall[],
  registry: RegisteredTool[],
): Promise<ToolResult[]> {
  const results: ToolResult[] = [];
  for (const call of calls) results.push(await executeToolCall(pool, call, registry));
  return results;
}

/** An error result for a tool call recovered from a truncated response. */
function failTruncated(call: ToolCall): ToolResult {
  return {
    toolCallId: call.id,
    isError: true,
    content: `Tool call '${call.name}' was NOT executed: the model response was truncated (stop reason 'length'), so its arguments may be incomplete and unsafe to run. Re-issue the call in a complete response.`,
  };
}

/** Wrap tool results in a `tool`-role conversation message. */
function toolResultsMessage(results: ToolResult[]): ConversationMessage {
  return { role: 'tool', content: '', toolResults: results };
}

/** The user-facing correction fed back on a malformed tool call. */
function reflectionMessage(error: ErrorEvent): string {
  return `Your previous tool call could not be used: ${error.message}. Please reissue it with valid, well-formed arguments.`;
}

/** Emit a stop event and return the loop's final result. */
function finish(stopReason: LoopOutcome, state: LoopState, ctx: LoopContext, detail: string): LoopResult {
  ctx.onEvent?.(loopEvent('stop', state.turns, detail));
  return { stopReason, messages: state.messages, turns: state.turns };
}

/** Whether an error event signals a malformed tool call (a reflection case). */
function isMalformedToolCall(event: ErrorEvent): boolean {
  return event.message.toLowerCase().includes('malformed');
}

/** Build a {@link LoopEvent}. */
function loopEvent(kind: LoopEvent['kind'], turn?: number, detail?: string): LoopEvent {
  return { type: 'loopEvent', kind, turn, detail };
}

/** Default real-timer sleep. */
function defaultSleep(ms: number): Promise<void> {
  return new Promise((resolve) => setTimeout(resolve, ms));
}
