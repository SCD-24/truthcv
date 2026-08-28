import { describe, it, expect } from 'vitest';
import {
  compact,
  estimateTokens,
  shouldCompact,
  KEEP_RECENT,
  PIN_LEADING,
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
    // Input only: the reply those output tokens paid for is appended to the
    // conversation before the next check, so it is counted in the tail
    // estimate instead. Counting both would count every assistant turn twice.
    const usage = { inputTokens: 800, outputTokens: 100 }; // 800 > 750
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
    // Pinned head, then the synthetic summary; the tail must match exactly.
    expect(out.slice(out.length - KEEP_RECENT)).toEqual(recent);
    expect(out.length).toBe(PIN_LEADING + 1 + KEEP_RECENT);
  });

  it('returns a record naming the dropped count', () => {
    // PIN_LEADING messages survive at the front, so a conversation of
    // KEEP_RECENT + n + PIN_LEADING drops n.
    const dropCount = 5;
    const messages = makeMessages(PIN_LEADING + KEEP_RECENT + dropCount);
    const { record } = compact(messages, config);
    expect(record).not.toBeNull();
    expect(record?.droppedMessageCount).toBe(dropCount);
    expect(record?.type).toBe('compaction');
    expect(typeof record?.summary).toBe('string');
    expect(record?.summary.length).toBeGreaterThan(0);
    expect(record?.summary).toContain(String(dropCount));
  });

  it('names the tools touched by dropped turns', () => {
    const messages = makeMessages(PIN_LEADING + KEEP_RECENT + 2);
    // Index 0 is pinned and never dropped, so the tool call under test has to
    // sit in the elided middle to appear in the summary at all.
    messages[PIN_LEADING] = { role: 'assistant', content: 'call', toolCalls: [{ id: '1', name: 'search', arguments: {} }] };
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

describe('what compaction must never drop', () => {
  const config: CompactionConfig = { contextWindow: 1000 };

  // The harness sends its operating instructions as the FIRST message
  // (cli.ts builds `initialMessages: [{ role: 'user', content: config.prompt }]`
  // and SYSTEM_PROMPT is ''), so the whole RUNBOOK — how to screen, the
  // truthfulness rules, which control to attach a document to — lives at
  // index 0. Dropping it leaves an agent still holding the browser and the
  // ledger tools but no longer told how to use them.
  it('keeps the first message, which carries the run instructions', () => {
    const messages = makeMessages(KEEP_RECENT + 5);
    messages[0] = { role: 'user', content: 'RUNBOOK: never apply without a cover letter.' };

    const { messages: out } = compact(messages, config);

    expect(out[0]).toEqual(messages[0]);
    expect(out.some((m) => m.content.includes('RUNBOOK'))).toBe(true);
  });

  it('counts only what it actually dropped', () => {
    // 11 messages in: 1 pinned + 6 kept recent = 7 survive, 4 are dropped.
    const messages = makeMessages(KEEP_RECENT + 5);

    const { record, messages: out } = compact(messages, config);

    expect(record?.droppedMessageCount).toBe(4);
    // pinned + summary + KEEP_RECENT
    expect(out.length).toBe(1 + 1 + KEEP_RECENT);
  });
});

describe('shouldCompact accounting', () => {
  // The docstring promises "any reported usage plus an estimate for the
  // untracked tail". Reported usage covers the prefix the provider has already
  // seen; the messages appended since are invisible to it. Taking usage alone
  // undercounts by exactly the turns most likely to be enormous — a fresh page
  // snapshot or a posting body just appended.
  it('adds an estimate of untracked messages to the reported usage', () => {
    const config: CompactionConfig = { contextWindow: 1000, reserveTokens: 0, triggerRatio: 0.75 };
    const usage = { inputTokens: 700, outputTokens: 0 }; // 700 < 750 on its own
    const tail = makeMessages(30); // ~300 estimated tokens appended since

    expect(shouldCompact([], usage, config)).toBe(false);
    expect(shouldCompact(tail, usage, config)).toBe(true);
  });
});

describe('compaction across a tool batch', () => {
  const config: CompactionConfig = { contextWindow: 1000 };

  // Both wires require a tool-results message to be immediately preceded by
  // the assistant turn that requested it. A fixed-offset cut lands inside a
  // batch whenever the batch is wider than the keep window, leaving a result
  // whose call was dropped — a 400 the provider does not let us retry, from
  // the compaction that was supposed to rescue the run.
  function batchedLog(): ConversationMessage[] {
    const call = (id: string) => ({ id, name: 'browser_navigate', arguments: {} });
    return [
      { role: 'user', content: 'RUNBOOK' },
      { role: 'assistant', content: '', toolCalls: [call('c1')] },
      { role: 'user', content: '', toolResults: [{ toolCallId: 'c1', content: 'ok' }] },
      { role: 'assistant', content: '', toolCalls: [call('c2')] },
      { role: 'user', content: '', toolResults: [{ toolCallId: 'c2', content: 'ok' }] },
      { role: 'user', content: 'WRAP UP' },
      { role: 'assistant', content: '', toolCalls: [call('c3')] },
      { role: 'user', content: '', toolResults: [{ toolCallId: 'c3', content: 'ok' }] },
      { role: 'assistant', content: '', toolCalls: [call('c4')] },
      { role: 'user', content: '', toolResults: [{ toolCallId: 'c4', content: 'ok' }] },
    ];
  }

  it('never keeps a tool result whose tool call it dropped', () => {
    const { messages: out } = compact(batchedLog(), config);

    const callIds = new Set(out.flatMap((m) => (m.toolCalls ?? []).map((c) => c.id)));
    const orphans = out
      .flatMap((m) => (m.toolResults ?? []).map((r) => r.toolCallId))
      .filter((id) => !callIds.has(id));

    expect(orphans).toEqual([]);
  });

  it('still drops something, rather than giving up to keep the batch whole', () => {
    const { record } = compact(batchedLog(), config);
    expect(record?.droppedMessageCount).toBeGreaterThan(0);
  });
});
