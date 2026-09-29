// Read-only projection of mixed stdout/stderr run logs. Never serialize source text.
import fs from 'node:fs';
import path from 'node:path';

export const SCHEMA_VERSION = 1;
export const DEFAULT_LIMIT = 50;
export const MAX_LIMIT = 200;
export const MAX_DIRECTORY_ENTRIES = 1024;
export const WINDOW_BYTES = 64 * 1024;
export const MAX_SCAN_BYTES = 512 * 1024;
export const MAX_RECORD_BYTES = 8 * 1024;
export const MAX_REPLY_BYTES = 256 * 1024;
const RUN_ID = /^[a-zA-Z0-9_-]{1,80}$/;
const LOG_NAME = /^run_\d{4}-\d{2}-\d{2}_\d{4}_(.+)\.log$/;
const STOP_REASONS = new Set(['toolCalls', 'end', 'length', 'error', 'aborted', 'turnCapReached']);
const LOOP_KINDS = new Set(['compaction', 'retry', 'reflection', 'emptyTurn',
  'turnCapReached', 'wrapUp', 'stop']);
const PROVIDERS = Object.freeze({ Anthropic: 'anthropic', OpenAI: 'openai',
  'OpenAI Responses': 'openai_responses', OpenRouter: 'openrouter', Ollama: 'ollama' });
const integer = (value, max) => Number.isSafeInteger(value) && value >= 0 && value <= max;
const record = (value) => value !== null && typeof value === 'object' && !Array.isArray(value);

function projectJson(line) {
  let source;
  try { source = JSON.parse(line); } catch { return null; }
  if (!record(source)) return null;
  if (source.type === 'error') {
    if (typeof source.message !== 'string') return null;
    const http = /^(Anthropic|OpenAI Responses|OpenAI|OpenRouter|Ollama) request failed with status ([1-5]\d\d)(?::| \(|$)/.exec(source.message);
    const network = /^(Anthropic|OpenAI Responses|OpenAI|OpenRouter|Ollama) request could not be sent:/.exec(source.message);
    const category = http ? 'provider_http' : network ? 'provider_network' : 'harness_error';
    return { category, summary: category === 'provider_http' ? 'Provider HTTP error' :
      category === 'provider_network' ? 'Provider network error' : 'Agent error',
    ...(http || network ? { provider: PROVIDERS[(http || network)[1]] } : {}),
    ...(http ? { http_status: Number(http[2]) } : {}),
    ...(typeof source.retryable === 'boolean' ? { retryable: source.retryable } : {}),
    ...(integer(source.retryAfterMs, 3_600_000) ? { retry_after_ms: source.retryAfterMs } : {}) };
  }
  if (source.type === 'loopEvent' && LOOP_KINDS.has(source.kind)) {
    return { category: 'loop_event', summary: 'Agent loop event', kind: source.kind,
      ...(integer(source.turn, 1_000_000) ? { turn: source.turn } : {}) };
  }
  if (source.type === 'done') {
    return { category: 'done', summary: 'Agent run ended',
      ...(STOP_REASONS.has(source.stopReason) ? { stop_reason: source.stopReason } : {}),
      ...(integer(source.turns, 1_000_000) ? { turns: source.turns } : {}),
      ...(integer(source.exitCode, 255) ? { exit_code: source.exitCode } : {}) };
  }
  if (source.type === 'toolResult' && source.isError === true) {
    return { category: 'tool_failure', summary: 'Agent tool failed' };
  }
  return null;
}

function projectLine(buffer) {
  // Fatal UTF-8 decoding prevents malformed byte sequences from masquerading as prefixes.
  let line;
  try { line = new TextDecoder('utf-8', { fatal: true }).decode(buffer); } catch { return null; }
  const text = line.replace(/^\d\d:\d\d:\d\d  /, '');
  if (text.startsWith('{')) return projectJson(text);
  const prefixes = [
    ['ABORT:', 'precondition', 'Agent precondition failed'],
    ['configuration error:', 'configuration', 'Agent configuration failed'],
    ['mcp connection failure:', 'mcp_connection', 'Agent tool connection failed'],
    ['provider error:', 'provider_error', 'Agent provider failed'],
    ['fatal:', 'fatal', 'Agent failed'],
  ];
  for (const [prefix, category, summary] of prefixes) {
    if (text.startsWith(prefix)) return { category, summary };
  }
  const exit = /^agent harness exited rc=(\d{1,3})$/.exec(text);
  if (exit && Number(exit[1]) <= 255) return { category: 'harness_exit',
    summary: 'Agent harness exited', exit_code: Number(exit[1]) };
  return null;
}

function findLog(directory, runId) {
  let dir;
  let found;
  let count = 0;
  try {
    dir = fs.opendirSync(directory);
    let entry;
    while ((entry = dir.readSync()) !== null) {
      if (++count > MAX_DIRECTORY_ENTRIES) return { reason: 'unreadable' };
      const match = LOG_NAME.exec(entry.name);
      if (match?.[1] !== runId) continue;
      if (found) return { reason: 'unreadable' }; // Ambiguous producer artifact.
      found = entry.name;
    }
    return found ? { file: path.join(directory, found) } : { reason: 'missing' };
  } catch { return { reason: 'unreadable' }; }
  finally { if (dir) try { dir.closeSync(); } catch { /* no writes */ } }
}

function scan(fd, end, limit, observedAt) {
  const excerpts = [];
  let cursor = end;
  let aligned = false;
  let reverse = [];
  let omitted = false;
  let bytes = 0;
  const collect = (offset) => {
    if (!reverse.length || reverse.length > MAX_RECORD_BYTES) { omitted = true; return; }
    const excerpt = projectLine(Buffer.from(reverse.reverse()));
    if (excerpt) excerpts.push({ offset, observed_at: observedAt, ...excerpt });
    else omitted = true;
  };
  while (cursor > 0 && excerpts.length < limit && bytes < MAX_SCAN_BYTES + MAX_RECORD_BYTES) {
    const length = Math.min(WINDOW_BYTES, cursor, MAX_SCAN_BYTES + MAX_RECORD_BYTES - bytes);
    const buffer = Buffer.alloc(length);
    const read = fs.readSync(fd, buffer, 0, length, cursor - length);
    if (read !== length) throw Error('short read');
    for (let i = length - 1; i >= 0; i--) {
      const position = cursor - length + i;
      if (buffer[i] === 10) {
        if (aligned) collect(position + 1);
        else if (position + 1 < end) omitted = true; // An unfinished append, not a complete record.
        aligned = true;
        reverse = [];
      } else if (aligned && reverse.length <= MAX_RECORD_BYTES) reverse.push(buffer[i]);
      else if (!aligned) omitted = true;
      if (excerpts.length === limit ||
        (end - position >= MAX_SCAN_BYTES && aligned && reverse.length === 0)) {
        return { excerpts, next: position + 1 > 0 ? position + 1 : null, omitted };
      }
    }
    cursor -= length;
    bytes += length;
  }
  if (cursor === 0 && aligned && reverse.length) collect(0);
  if (cursor > 0 && reverse.length) omitted = true; // Bounded scan stopped inside a record.
  return { excerpts, next: cursor > 0 ? cursor : null, omitted };
}

/** Project only fixed diagnostic categories from a producer-named log; never expose source strings. */
export function readRunLogExcerpts(directory, runId, options = {}) {
  const { limit = DEFAULT_LIMIT, beforeOffset } = options;
  if (typeof runId !== 'string' || !RUN_ID.test(runId)) throw new RangeError('invalid run_id');
  if (!Number.isSafeInteger(limit) || limit < 1 || limit > MAX_LIMIT ||
    (beforeOffset !== undefined && (!Number.isSafeInteger(beforeOffset) || beforeOffset < 1))) {
    throw new RangeError('invalid pagination');
  }
  const base = { schema_version: SCHEMA_VERSION, run_id: runId };
  const unavailable = (reason) => ({ ...base, availability: 'unavailable', reason,
    excerpts: [], next_before_offset: null, truncated: false, omitted: false });
  const located = findLog(directory, runId);
  if (located.reason) return unavailable(located.reason);
  let fd;
  try {
    fd = fs.openSync(located.file, fs.constants.O_RDONLY | fs.constants.O_NOFOLLOW | fs.constants.O_NONBLOCK);
    const stat = fs.fstatSync(fd);
    if (!stat.isFile()) return unavailable('unreadable');
    const end = stat.size; // Freeze the pagination view before any descriptor reads.
    if (beforeOffset !== undefined && beforeOffset > end) throw new RangeError('invalid pagination');
    const page = scan(fd, beforeOffset ?? end, limit, new Date().toISOString());
    const reply = { ...base, availability: 'available', reason: null, excerpts: page.excerpts,
      next_before_offset: page.next, truncated: page.next !== null, omitted: page.omitted };
    if (Buffer.byteLength(JSON.stringify(reply)) > MAX_REPLY_BYTES) return unavailable('unreadable');
    return reply;
  } catch (err) {
    if (err instanceof RangeError) throw err;
    return unavailable(err.code === 'ENOENT' ? 'missing' : 'unreadable');
  } finally { if (fd !== undefined) try { fs.closeSync(fd); } catch { /* no writes */ } }
}
