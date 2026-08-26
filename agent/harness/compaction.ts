/**
 * Conversation-history compaction with an explicit escape hatch for
 * local models whose context window we cannot discover.
 *
 * The harness trims older turns once the running token estimate approaches
 * the model's context window, replacing them with a single auditable summary
 * message so a run log still shows exactly what was dropped.
 */

import type { ConversationMessage } from './providers/types.js';

/** Token accounting reported by a provider for the tracked prefix. */
export interface TokenUsage {
  /** Tokens consumed by the prompt / input side. */
  inputTokens: number;
  /** Tokens produced on the output side. */
  outputTokens: number;
}

/**
 * Tuning for when and how aggressively to compact.
 *
 * `contextWindow` is the model's total context size in tokens. A value of 0
 * (or any falsy/unknown value) is the deliberate escape hatch: it means the
 * window is unknown — as with a local model we cannot introspect — and
 * compaction is disabled entirely rather than guessed at.
 */
export interface CompactionConfig {
  /** Model's total context size in tokens; 0/falsy disables compaction. */
  contextWindow: number;
  /** Headroom reserved for the next response. Defaults to 2000. */
  reserveTokens?: number;
  /** Fraction of contextWindow at which compaction triggers. Defaults to 0.75. */
  triggerRatio?: number;
}

/** Number of most-recent messages that are never compacted away. */
export const KEEP_RECENT = 6;

/** Default headroom reserved for the next model response, in tokens. */
const DEFAULT_RESERVE_TOKENS = 2000;

/** Default fraction of the context window at which compaction kicks in. */
const DEFAULT_TRIGGER_RATIO = 0.75;

/**
 * Deterministic, rough token estimate for text that carries no reported usage.
 *
 * This is an estimate for the untracked tail of the conversation, not an exact
 * count — roughly four characters per token.
 */
export function estimateTokens(text: string): number {
  return Math.ceil(text.length / 4);
}

/** Estimated token cost of a message: its content plus any tool payloads. */
function messageTokens(message: ConversationMessage): number {
  const toolCalls = (message.toolCalls ?? []).map((c) => JSON.stringify(c.arguments)).join('');
  const toolResults = (message.toolResults ?? []).map((r) => r.content).join('');
  return estimateTokens(message.content + toolCalls + toolResults);
}

/**
 * Decide whether the conversation is large enough to warrant compaction.
 *
 * Returns false immediately when `contextWindow` is falsy (the escape hatch —
 * we do not guess for unknown-window models). Otherwise it sums any reported
 * usage plus an estimate for the untracked tail of messages and compares the
 * total against `contextWindow * triggerRatio`.
 */
export function shouldCompact(
  messages: ConversationMessage[],
  reportedUsage: TokenUsage | undefined,
  config: CompactionConfig,
): boolean {
  if (!config.contextWindow) return false;
  const reserve = config.reserveTokens ?? DEFAULT_RESERVE_TOKENS;
  const ratio = config.triggerRatio ?? DEFAULT_TRIGGER_RATIO;
  let total = reserve;
  if (reportedUsage) {
    total += reportedUsage.inputTokens + reportedUsage.outputTokens;
  } else {
    total += messages.reduce((sum, m) => sum + messageTokens(m), 0);
  }
  return total > config.contextWindow * ratio;
}

/**
 * An auditable record of a single compaction, for the caller to log.
 *
 * This is intentionally separate from the message list so a run log shows
 * exactly how many turns were summarised away and what they contained.
 */
export interface CompactionRecord {
  /** Discriminant marking this as a compaction event. */
  type: 'compaction';
  /** How many older messages were removed from the history. */
  droppedMessageCount: number;
  /** Human-readable summary naming the dropped count and topics. */
  summary: string;
}

/** Best-effort list of distinct tool names referenced across messages. */
function toolNames(messages: ConversationMessage[]): string[] {
  const names = new Set<string>();
  for (const message of messages) {
    for (const call of message.toolCalls ?? []) names.add(call.name);
  }
  return [...names];
}

/** Build the mechanical, auditable summary text for the dropped turns. */
function summarise(dropped: ConversationMessage[]): string {
  const tools = toolNames(dropped);
  const suffix = tools.length ? ` covering tool calls: ${tools.join(', ')}` : '';
  return `Summarized ${dropped.length} earlier turns (dropped)${suffix}.`;
}

/**
 * Compact the conversation, keeping the most recent {@link KEEP_RECENT}
 * messages byte-identical and folding everything older into one synthetic
 * `system` summary message.
 *
 * Safe to call unconditionally: when there are not more than the keep-minimum
 * messages there is nothing to drop, so it returns the messages unchanged and
 * a null record. Callers are still expected to gate on {@link shouldCompact}.
 */
export function compact(
  messages: ConversationMessage[],
  _config: CompactionConfig,
): { messages: ConversationMessage[]; record: CompactionRecord | null } {
  if (messages.length <= KEEP_RECENT) {
    return { messages, record: null };
  }
  const dropped = messages.slice(0, messages.length - KEEP_RECENT);
  const kept = messages.slice(messages.length - KEEP_RECENT);
  const summary = summarise(dropped);
  const summaryMessage: ConversationMessage = { role: 'system', content: `[compaction] ${summary}` };
  const record: CompactionRecord = { type: 'compaction', droppedMessageCount: dropped.length, summary };
  return { messages: [summaryMessage, ...kept], record };
}
