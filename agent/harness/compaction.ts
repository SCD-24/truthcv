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

/**
 * Number of leading messages never compacted away.
 *
 * The harness delivers its operating instructions as the first message — cli.ts
 * builds `initialMessages: [{ role: 'user', content: config.prompt }]` and
 * SYSTEM_PROMPT is '' — so the run's whole RUNBOOK lives at index 0. Dropping
 * it leaves an agent still holding the browser and the ledger tools but told
 * nothing about how to use them: it keeps going, which is worse than stopping,
 * because the run looks alive while nothing constrains it.
 */
export const PIN_LEADING = 1;

/** Default headroom reserved for the next model response, in tokens. */
const DEFAULT_RESERVE_TOKENS = 2000;

/** Default fraction of the context window at which compaction kicks in. */
const DEFAULT_TRIGGER_RATIO = 0.75;

/**
 * Conservative context-window fallback used by the CLI when the operator
 * states none.
 *
 * The trade-off is asymmetric, not a guess split down the middle. A fallback
 * that is too HIGH is rescued by the reactive `compactAndRetry` path: the
 * provider itself will say the context is too long, and the loop compacts and
 * resends — a normal, bounded recovery already exercised on every provider. A
 * fallback that is too LOW has no such backstop: it compacts every few turns
 * for no reason, silently discarding context that would have fit, and nothing
 * ever overflows to reveal the loss. So this number is deliberately generous
 * — comfortably under context windows real hosted models ship with today, so
 * proactive compaction still does useful work rather than never firing, while
 * staying far above the point where it would routinely fire and shed history
 * that fit fine.
 */
export const DEFAULT_FALLBACK_CONTEXT_WINDOW = 32768;

/**
 * Deterministic, rough token estimate for text that carries no reported usage.
 *
 * This is an estimate for the untracked tail of the conversation, not an exact
 * count — roughly four characters per token.
 */
export function estimateTokens(text: string): number {
  return Math.ceil(text.length / 4);
}

/**
 * Move a cut point back until it does not split a tool batch.
 *
 * Both wires require a message carrying tool results to be immediately
 * preceded by the assistant turn that requested them. An agentic log's tail is
 * always `assistant(toolCalls), tool, tool, …`, so a fixed-offset cut lands
 * inside such a run whenever the batch is wider than the keep window — leaving
 * a tool result whose tool call has been dropped. The provider answers 400
 * ("unexpected tool_use_id"), which is not retryable, so the compaction that
 * was meant to rescue the run ends it instead, having already discarded the
 * history.
 *
 * Walking backward — rather than forward, or giving up — matters for the
 * reason it is called from: the reactive path compacts BECAUSE the context
 * overflowed, so a tighter keep window must never be more likely to fail than
 * a loose one. Bounded at the pinned head, which is never a tool result.
 */
function pairedBoundary(messages: ConversationMessage[], from: number): number {
  let boundary = from;
  while (boundary > PIN_LEADING && (messages[boundary]?.toolResults?.length ?? 0) > 0) {
    boundary -= 1;
  }
  return boundary;
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
 * usage for the prefix it has already seen, PLUS an estimate for the messages
 * appended since, and compares the total against `contextWindow * triggerRatio`.
 *
 * Both terms are needed. Usage describes a request already sent, so it misses
 * everything added since — and what gets added between two requests is a page
 * snapshot or a posting body, the largest single additions this agent makes.
 * The estimate alone throws away the one exact number the provider gives us.
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
  // Input only. The reply those output tokens paid for is appended to the
  // conversation before the next check, so it is already inside the estimated
  // tail — adding outputTokens as well counts every assistant turn twice.
  if (reportedUsage) total += reportedUsage.inputTokens;
  total += messages.reduce((sum, m) => sum + messageTokens(m), 0);
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
  /**
   * The summary text actually used in the synthetic message: the caller's
   * override (e.g. model-generated) when {@link compact} was given one,
   * otherwise the mechanical summary computed here.
   */
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

/** The would-be split of a compaction, without mutating anything or building a summary. */
export interface CompactionPlan {
  /** Messages that would be kept verbatim at the head. */
  pinned: ConversationMessage[];
  /** Messages that would be dropped and folded into the summary. */
  dropped: ConversationMessage[];
  /** Messages that would be kept verbatim at the tail. */
  kept: ConversationMessage[];
}

/**
 * Compute the {@link PIN_LEADING}/pairedBoundary/{@link KEEP_RECENT} split
 * {@link compact} itself uses, without mutating anything or building a
 * summary. Exposed so a caller can inspect — or render, for a model-generated
 * summary — the turns about to be dropped BEFORE {@link compact} commits to
 * removing them.
 *
 * Returns null exactly when {@link compact} itself would no-op: too few
 * messages, or a batch-preserving boundary that leaves nothing between the
 * pinned head and the kept tail — so the two never disagree about whether
 * there is anything to drop.
 */
export function planCompaction(messages: ConversationMessage[]): CompactionPlan | null {
  if (messages.length <= PIN_LEADING + KEEP_RECENT) return null;
  const keepFrom = pairedBoundary(messages, messages.length - KEEP_RECENT);
  const pinned = messages.slice(0, PIN_LEADING);
  const dropped = messages.slice(PIN_LEADING, keepFrom);
  const kept = messages.slice(keepFrom);
  // Moving the boundary back to keep a batch whole can leave nothing between
  // the pinned head and the kept tail. Saying so, rather than describing a
  // drop of nothing, is what lets a caller tell "there is something to
  // compact" from "already at its floor".
  if (dropped.length === 0) return null;
  return { pinned, dropped, kept };
}

/** Max characters of the bounded transcript rendered for a model summarizer. */
const MAX_TRANSCRIPT_CHARS = 8000;

/**
 * Render dropped turns into a bounded, plain-text transcript for a model
 * summarizer to read.
 *
 * Reuses the same content + tool-call + tool-result extraction {@link
 * messageTokens} uses for token accounting, because that is exactly what a
 * turn "cost" and exactly what a summary needs to describe. Bounded by total
 * characters, not just per-message: the summarizer's own request could itself
 * overflow if handed the whole dropped range verbatim — which would make the
 * compaction summarizer the thing that causes the very problem compaction
 * exists to solve.
 *
 * @param dropped The turns {@link planCompaction} identified as about to be dropped.
 * @param maxChars Character budget for the rendered transcript.
 */
export function renderDroppedTranscript(dropped: ConversationMessage[], maxChars = MAX_TRANSCRIPT_CHARS): string {
  const lines: string[] = [];
  let total = 0;
  for (const message of dropped) {
    const toolCalls = (message.toolCalls ?? []).map((c) => `${c.name}(${JSON.stringify(c.arguments)})`).join(', ');
    const toolResults = (message.toolResults ?? []).map((r) => r.content).join(' ');
    const body = [message.content, toolCalls, toolResults].filter(Boolean).join(' ');
    const line = `[${message.role}] ${body}`.trim();
    if (!line) continue;
    if (total + line.length > maxChars) {
      lines.push('[transcript truncated]');
      break;
    }
    lines.push(line);
    total += line.length;
  }
  return lines.join('\n');
}

/**
 * Compact the conversation, keeping the first {@link PIN_LEADING} messages and
 * the most recent {@link KEEP_RECENT} byte-identical, and folding everything
 * between them into one synthetic `system` summary message.
 *
 * Safe to call unconditionally: when there are not more than the keep-minimum
 * messages there is nothing to drop, so it returns the messages unchanged and
 * a null record. Callers are still expected to gate on {@link shouldCompact}.
 *
 * `summaryText`, when given and non-blank, replaces the mechanical {@link
 * summarise} text verbatim in the synthetic message and the returned record.
 * This function stays pure and synchronous either way — producing a
 * model-generated summary, and deciding whether it is good enough to use, is
 * entirely the caller's job (see loop.ts's `applyCompaction`).
 */
export function compact(
  messages: ConversationMessage[],
  _config: CompactionConfig,
  summaryText?: string,
): { messages: ConversationMessage[]; record: CompactionRecord | null } {
  const plan = planCompaction(messages);
  if (!plan) return { messages, record: null };
  const { pinned, dropped, kept } = plan;
  const summary = summaryText?.trim() ? summaryText.trim() : summarise(dropped);
  const summaryMessage: ConversationMessage = { role: 'system', content: `[compaction] ${summary}` };
  const record: CompactionRecord = { type: 'compaction', droppedMessageCount: dropped.length, summary };
  return { messages: [...pinned, summaryMessage, ...kept], record };
}
