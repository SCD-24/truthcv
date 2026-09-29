import { describe, it, expect } from 'vitest';
import { mkdtempSync, writeFileSync, appendFileSync, symlinkSync, rmSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { execFileSync } from 'node:child_process';
// @ts-expect-error standalone supervisor module has no declaration file
import { readRunLogExcerpts } from '../run-log-excerpts.mjs';

const secret = 'pat@example.com https://private.example/?token=secret phone 555-1212';
const name = (dir: string, id: string, stamp = '2025-01-02_0304') => join(dir, `run_${stamp}_${id}.log`);
const read = (dir: string, id = 'sample', options = {}) => readRunLogExcerpts(dir, id, options);

describe('sanitized run log excerpts', () => {
  it('projects real CLI and shell shapes, never content, even in unknown fields', () => {
    const dir = mkdtempSync(join(tmpdir(), 'run-excerpts-'));
    try {
      writeFileSync(name(dir, 'sample'), [
        `12:00:00  ABORT: browser MCP server unreachable at ${secret}`,
        `configuration error: ${secret}`,
        JSON.stringify({ type: 'error', message: `OpenAI request failed with status 429: ${secret}`,
          retryable: true, retryAfterMs: 1000, body: secret }),
        JSON.stringify({ type: 'error', message: `Anthropic request could not be sent: ${secret}`, retryable: true }),
        JSON.stringify({ type: 'loopEvent', kind: 'retry', turn: 4, detail: secret }),
        JSON.stringify({ type: 'toolResult', namespacedName: secret, content: secret, isError: true }),
        JSON.stringify({ type: 'done', stopReason: 'error', turns: 4, exitCode: 3, body: secret }),
        '12:00:00  agent harness exited rc=3', '',
      ].join('\n'));
      const result = read(dir);
      expect(result).toMatchObject({ availability: 'available', omitted: false, truncated: false,
        next_before_offset: null });
      expect(result.excerpts.every((e: { observed_at: string }) =>
        /^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d\.\d{3}Z$/.test(e.observed_at) &&
        !Number.isNaN(Date.parse(e.observed_at)))).toBe(true);
      expect(result.excerpts.map((e: { category: string }) => e.category)).toEqual([
        'harness_exit', 'done', 'tool_failure', 'loop_event', 'provider_network',
        'provider_http', 'configuration', 'precondition',
      ]);
      expect(result.excerpts.find((e: { category: string }) => e.category === 'provider_http'))
        .toMatchObject({ provider: 'openai', http_status: 429, retryable: true, retry_after_ms: 1000 });
      expect(result.excerpts.find((e: { category: string }) => e.category === 'provider_network'))
        .toMatchObject({ provider: 'anthropic', retryable: true });
      expect(JSON.stringify(result)).not.toContain(secret);
      expect(Buffer.byteLength(JSON.stringify(result))).toBeLessThanOrEqual(256 * 1024);
    } finally { rmSync(dir, { recursive: true, force: true }); }
  });

  it('maps only exact producer labels to finite provider enums for HTTP and network errors', () => {
    const dir = mkdtempSync(join(tmpdir(), 'run-excerpts-'));
    try {
      const labels = [
        ['Anthropic', 'anthropic'], ['OpenAI', 'openai'],
        ['OpenAI Responses', 'openai_responses'], ['OpenRouter', 'openrouter'],
        ['Ollama', 'ollama'],
      ];
      writeFileSync(name(dir, 'sample'), [
        ...labels.flatMap(([label]) => [
          JSON.stringify({ type: 'error', message: `${label} request failed with status 429: ${secret}` }),
          JSON.stringify({ type: 'error', message: `${label} request could not be sent: ${secret}` }),
        ]),
        JSON.stringify({ type: 'error', message: `codex request failed with status 429: ${secret}` }),
        JSON.stringify({ type: 'error', message: `anthropic request could not be sent: ${secret}` }),
        '',
      ].join('\n'));
      const excerpts = read(dir).excerpts;
      expect(excerpts.slice(0, 2)).toMatchObject([
        { category: 'harness_error' }, { category: 'harness_error' },
      ]);
      expect(excerpts.slice(0, 2).every((e: { provider?: string }) => e.provider === undefined)).toBe(true);
      expect(excerpts.slice(2).map((e: { category: string; provider: string; http_status?: number }) =>
        ({ category: e.category, provider: e.provider, http_status: e.http_status })))
        .toEqual(labels.slice().reverse().flatMap(([, provider]) => [
          { category: 'provider_network', provider, http_status: undefined },
          { category: 'provider_http', provider, http_status: 429 },
        ]));
      expect(JSON.stringify(excerpts)).not.toContain(secret);
    } finally { rmSync(dir, { recursive: true, force: true }); }
  });

  it('drops unknown, invalid, partial and oversized records and keeps unicode boundaries', () => {
    const dir = mkdtempSync(join(tmpdir(), 'run-excerpts-'));
    try {
      writeFileSync(name(dir, 'sample'), [JSON.stringify({ type: 'toolCall', content: secret }),
        JSON.stringify({ type: 'error', message: `😀 ${secret}`, retryable: 'true', retryAfterMs: Infinity }),
        '{not json', 'x'.repeat(9000), JSON.stringify({ type: 'loopEvent', kind: secret, detail: secret }),
        JSON.stringify({ type: 'loopEvent', kind: 'stop', turn: 2, detail: secret }),
        `{"type":"error","message":"${secret}`, // unterminated tail
      ].join('\n'));
      const result = read(dir);
      expect(result.omitted).toBe(true);
      expect(result.truncated).toBe(false);
      expect(result.excerpts.map((e: { category: string }) => e.category)).toEqual(['loop_event', 'harness_error']);
      expect(result.excerpts[1]).not.toHaveProperty('retryable');
      expect(JSON.stringify(result)).not.toContain(secret);
      expect(read(dir, 'absent')).toMatchObject({ availability: 'unavailable', reason: 'missing',
        omitted: false, truncated: false, excerpts: [], next_before_offset: null });
      expect(() => read(dir, 'sample', { beforeOffset: 99999999 })).toThrow(RangeError);
    } finally { rmSync(dir, { recursive: true, force: true }); }
  });

  it('paginates strictly backward from snapshot offsets when the producer appends', () => {
    const dir = mkdtempSync(join(tmpdir(), 'run-excerpts-'));
    try {
      const file = name(dir, 'sample');
      writeFileSync(file, Array.from({ length: 220 }, (_, i) => JSON.stringify({ type: 'loopEvent',
        kind: 'retry', turn: i, detail: secret })).join('\n') + '\n');
      const first = read(dir, 'sample', { limit: 10 });
      appendFileSync(file, JSON.stringify({ type: 'done', exitCode: 0 }) + '\n');
      const second = read(dir, 'sample', { limit: 10, beforeOffset: first.next_before_offset });
      expect(first.excerpts.map((e: { turn: number }) => e.turn)).toEqual([219, 218, 217, 216, 215, 214, 213, 212, 211, 210]);
      expect(second.excerpts[0].turn).toBe(209);
      expect(second.next_before_offset).toBeLessThan(first.next_before_offset);
      expect(first).toMatchObject({ omitted: false, truncated: true });
      expect(second).toMatchObject({ omitted: false, truncated: true });
      expect(() => read(dir, 'sample', { beforeOffset: 0 })).toThrow(RangeError);
      expect(() => read(dir, '../escape')).toThrow(RangeError);
      expect(() => read(dir, 'sample', { limit: 201 })).toThrow(RangeError);
    } finally { rmSync(dir, { recursive: true, force: true }); }
  });

  it('bounds scans of huge files while preserving a progressing empty page', () => {
    const dir = mkdtempSync(join(tmpdir(), 'run-excerpts-'));
    try {
      writeFileSync(name(dir, 'sample'), ('ignored arbitrary text ' + secret + '\n').repeat(100_000));
      const page = read(dir);
      expect(page).toMatchObject({ availability: 'available', excerpts: [], truncated: true,
        omitted: true });
      expect(page.next_before_offset).toBeGreaterThan(0);
      expect(read(dir, 'sample', { beforeOffset: page.next_before_offset }).next_before_offset)
        .toBeLessThan(page.next_before_offset);
      expect(JSON.stringify(page)).not.toContain(secret);
    } finally { rmSync(dir, { recursive: true, force: true }); }
  });

  it('discards incomplete and oversized records without leaking boundary fragments', () => {
    const dir = mkdtempSync(join(tmpdir(), 'run-excerpts-'));
    try {
      const file = name(dir, 'sample');
      writeFileSync(file, Buffer.concat([
        Buffer.from('{"type":"done","exitCode":2}\n'),
        Buffer.from('x'.repeat(9000) + '\n'),
        Buffer.from([0xff, 0xfe, 10]),
        Buffer.from('{"type":"error","message":"' + secret),
      ]));
      const page = read(dir);
      expect(page).toMatchObject({ availability: 'available', omitted: true,
        truncated: false, next_before_offset: null });
      expect(page.excerpts).toMatchObject([{ category: 'done', exit_code: 2, offset: 0 }]);
      expect(JSON.stringify(page)).not.toContain(secret);
      appendFileSync(file, '"}\n');
      expect(read(dir).excerpts[0].category).toBe('harness_error');
      const capped = name(dir, 'capped');
      writeFileSync(capped, 'x'.repeat(600_000) + '\n');
      const first = read(dir, 'capped');
      expect(first).toMatchObject({ excerpts: [], omitted: true, truncated: true });
      expect(first.next_before_offset).toBeGreaterThan(0);
      expect(read(dir, 'capped', { beforeOffset: first.next_before_offset }))
        .toMatchObject({ next_before_offset: null, truncated: false, omitted: true, excerpts: [] });
    } finally { rmSync(dir, { recursive: true, force: true }); }
  });

  it('rejects ambiguous, symlinked and nonregular artifacts and caps enumeration', () => {
    const dir = mkdtempSync(join(tmpdir(), 'run-excerpts-'));
    try {
      const file = name(dir, 'sample');
      writeFileSync(file, '{"type":"done"}\n');
      writeFileSync(name(dir, 'sample', '2025-01-02_0305'), '{"type":"done"}\n');
      expect(read(dir).availability).toBe('unavailable');
      symlinkSync(file, name(dir, 'link'));
      expect(read(dir, 'link').reason).toBe('unreadable');
      execFileSync('mkfifo', [name(dir, 'pipe')]);
      expect(read(dir, 'pipe').reason).toBe('unreadable');
      writeFileSync(name(dir, 'filtered'), 'unknown line\n');
      expect(read(dir, 'filtered')).toMatchObject({ availability: 'available', excerpts: [],
        omitted: true, truncated: false });
      writeFileSync(name(dir, 'empty'), '');
      expect(read(dir, 'empty')).toMatchObject({ availability: 'available', excerpts: [],
        omitted: false, truncated: false });
      for (let i = 0; i < 1025; i++) writeFileSync(join(dir, `other_${i}`), '');
      expect(read(dir, 'missing').reason).toBe('unreadable');
    } finally { rmSync(dir, { recursive: true, force: true }); }
  });
});
