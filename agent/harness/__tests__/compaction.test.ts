import { describe, it, expect } from 'vitest';
import {
  compact,
  estimateTokens,
  shouldCompact,
  KEEP_RECENT,
  type CompactionConfig,
} from '../compaction.js';
import type { ConversationMessage } from '../providers/types.js';

function msg(role: ConversationMessage['role'], content: string): ConversationMessage {
  return { role, content };
}

function makeMessages(count: number, size = 40): ConversationMessage[] {
  return Array.from({ length: count }, (_, i) =>
    msg(i % 2 === 0 ? 'user' : 'assistant', `m${i}:${'x'.repeat(size)}`),
  );
}

describe('estimateTokens', () => {
  it('estimates roughly four characters per token', () => {
    expect(estimateTokens('')).toBe(0);
    expect(estimateTokens('abcd')).toBe(1);
    expect(estimateTokens('abcde')).toBe(2);
  });
});

describe('shouldCompact escape hatch', () => {
  it('returns false when contextWindow is 0 no matter how large the input', () => {
    const config: CompactionConfig = { contextWindow: 0 };
    const huge = makeMessages(1000, 4000);
    const usage = { inputTokens: 10_000_000, outputTokens: 10_000_000 };
    expect(shouldCompact(huge, usage, config)).toBe(false);
    expect(shouldCompact(huge, undefined, config)).toBe(false);
  });
});

describe('shouldCompact threshold', () => {
  const config: CompactionConfig = { contextWindow: 1000, reserveTokens: 0, triggerRatio: 0.75 };

  it('returns true once accumulated tokens exceed contextWindow * triggerRatio', () => {
    const usage = { inputTokens: 700, outputTokens: 100 }; // 800 > 750
    expect(shouldCompact([], usage, config)).toBe(true);
  });

  it('returns false when comfortably under the threshold', () => {
    const usage = { inputTokens: 200, outputTokens: 100 }; // 300 < 750
    expect(shouldCompact([], usage, config)).toBe(false);
  });

  it('falls back to estimateTokens when no usage is reported', () => {
    // 300 messages of ~10 tokens each ≈ 3000 tokens > 750.
    expect(shouldCompact(makeMessages(300), undefined, config)).toBe(true);
    expect(shouldCompact(makeMessages(2), undefined, config)).toBe(false);
  });
});

describe('compact', () => {
  const config: CompactionConfig = { contextWindow: 1000 };

  it('leaves the most recent KEEP_RECENT turns byte-identical', () => {
    const messages = makeMessages(KEEP_RECENT + 4);
    const recent = messages.slice(messages.length - KEEP_RECENT);
    const { messages: out } = compact(messages, config);
    // First entry is the synthetic summary; the tail must match exactly.
    expect(out.slice(out.length - KEEP_RECENT)).toEqual(recent);
    expect(out.length).toBe(KEEP_RECENT + 1);
  });

  it('returns a record naming the dropped count', () => {
    const dropCount = 5;
    const messages = makeMessages(KEEP_RECENT + dropCount);
    const { record } = compact(messages, config);
    expect(record).not.toBeNull();
    expect(record?.droppedMessageCount).toBe(dropCount);
    expect(record?.type).toBe('compaction');
    expect(typeof record?.summary).toBe('string');
    expect(record?.summary.length).toBeGreaterThan(0);
    expect(record?.summary).toContain(String(dropCount));
  });

  it('names the tools touched by dropped turns', () => {
    const messages = makeMessages(KEEP_RECENT + 2);
    messages[0] = { role: 'assistant', content: 'call', toolCalls: [{ id: '1', name: 'search', arguments: {} }] };
    const { record } = compact(messages, config);
    expect(record?.summary).toContain('search');
  });

  it('is a no-op when there are fewer messages than the keep-minimum', () => {
    const messages = makeMessages(KEEP_RECENT);
    const { messages: out, record } = compact(messages, config);
    expect(record).toBeNull();
    expect(out).toBe(messages);
  });
});
