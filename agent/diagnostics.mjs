// Dedicated, bounded, metadata-only diagnostics reader. Never consult raw run logs.
import fs from 'node:fs';
import path from 'node:path';

export const SCHEMA_VERSION = 1;
const MAX_FILE_BYTES = 2 * 1024 * 1024;
const MAX_REPLY_BYTES = 256 * 1024;
const RUN_ID = /^[a-zA-Z0-9_-]{1,80}$/;
const OP_ID = /^[a-zA-Z0-9_-]{1,80}$/;
const TOOL_NAME = /^[a-zA-Z0-9_]{1,80}$/;
const PHASES = new Set(['registry_refresh', 'compaction', 'model', 'tool', 'backoff']);
const STATUSES = new Set(['start', 'success', 'error']);
const eventKeys = new Set(['schema_version', 'run_id', 'sequence', 'at', 'operation_id', 'phase', 'status',
  'duration_ms', 'tool_name', 'turn', 'retry_attempt', 'delay_ms', 'active_operations', 'active_truncated', 'truncated']);
const activeKeys = new Set(['operation_id', 'phase', 'started_at', 'tool_name', 'turn']);
const record = (value) => value !== null && typeof value === 'object' && !Array.isArray(value);
const keysAllowed = (value, keys) => Object.keys(value).every((key) => keys.has(key));
const nonnegative = (value) => Number.isSafeInteger(value) && value >= 0;
const timestamp = (value) => typeof value === 'string' && /^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d\.\d{3}Z$/.test(value)
  && !Number.isNaN(Date.parse(value)) && new Date(value).toISOString() === value;

function validActive(op) {
  return record(op) && keysAllowed(op, activeKeys) && typeof op.operation_id === 'string'
    && OP_ID.test(op.operation_id) && PHASES.has(op.phase)
    && timestamp(op.started_at) && (op.tool_name === undefined || (op.phase === 'tool'
      && typeof op.tool_name === 'string' && TOOL_NAME.test(op.tool_name)))
    && (op.turn === undefined || nonnegative(op.turn));
}

function validEvent(event, runId) {
  return record(event) && keysAllowed(event, eventKeys) && event.schema_version === SCHEMA_VERSION
    && event.run_id === runId && Number.isSafeInteger(event.sequence) && event.sequence > 0
    && timestamp(event.at) && typeof event.operation_id === 'string'
    && OP_ID.test(event.operation_id) && PHASES.has(event.phase)
    && STATUSES.has(event.status) && typeof event.active_truncated === 'boolean'
    && typeof event.truncated === 'boolean' && Array.isArray(event.active_operations)
    && event.active_operations.length <= 128 && event.active_operations.every(validActive)
    && (event.tool_name === undefined || (event.phase === 'tool'
      && typeof event.tool_name === 'string' && TOOL_NAME.test(event.tool_name)))
    && (event.duration_ms === undefined || (event.status !== 'start' && nonnegative(event.duration_ms)))
    && (event.turn === undefined || nonnegative(event.turn))
    && (event.retry_attempt === undefined || nonnegative(event.retry_attempt))
    && (event.delay_ms === undefined || nonnegative(event.delay_ms));
}

/**
 * @param {string} directory  Trusted run artifact directory.
 * @param {string} runId
 * @param {{limit?: number, beforeSequence?: number, running?: boolean, currentRunId?: string|null, health?: {healthy: boolean, sequence: number}|null|(() => {healthy: boolean, sequence: number}|null)}} options
 */
export function readRunDiagnostics(directory, runId, options = {}) {
  const { limit = 50, beforeSequence, running = false, currentRunId = null, health = null } = options;
  const live = running && currentRunId === runId;
  const missingHealth = () => live ? 'telemetry_unavailable' : 'missing';
  const sampleHealth = () => typeof health === 'function' ? health() : health;
  if (typeof runId !== 'string' || !RUN_ID.test(runId)) throw new RangeError('invalid run_id');
  if (!Number.isSafeInteger(limit) || limit < 1 || limit > 200
    || (beforeSequence !== undefined && (!Number.isSafeInteger(beforeSequence) || beforeSequence < 1))) {
    throw new RangeError('invalid pagination');
  }
  const base = { schema_version: SCHEMA_VERSION, run_id: runId, running: Boolean(running), currentRunId,
    observed_at: new Date().toISOString() };
  const unavailable = (reason) => ({ ...base, availability: 'unavailable', reason, events: [],
    next_before_sequence: null, truncated: false, last_activity_at: null,
    active_operations: [], active_truncated: false });
  // A known failed current-child lease takes precedence over stale or broken disk artifacts.
  const fileUnavailable = (reason) => unavailable(live && sampleHealth()?.healthy === false
    ? 'telemetry_unavailable' : reason);
  if (live && sampleHealth()?.healthy === false) return unavailable('telemetry_unavailable');
  const file = path.join(directory, `diagnostics_${runId}.ndjson`);
  let fd;
  let data;
  try {
    // O_NOFOLLOW rejects symlinks at the final component, including a swap
    // after lstat. Read from that same descriptor so the check and read agree.
    fd = fs.openSync(file, fs.constants.O_RDONLY | fs.constants.O_NOFOLLOW);
    const stat = fs.fstatSync(fd);
    if (!stat.isFile() || stat.size > MAX_FILE_BYTES || stat.size === 0) return fileUnavailable('malformed');
    const buffer = Buffer.alloc(stat.size);
    const count = fs.readSync(fd, buffer, 0, buffer.length, 0);
    data = buffer.subarray(0, count).toString('utf8');
  } catch (err) {
    return fileUnavailable(err.code === 'ENOENT' ? missingHealth() : 'unreadable');
  } finally {
    if (fd !== undefined) {
      try { fs.closeSync(fd); } catch { /* diagnostics must not break the control server */ }
    }
  }
  // The writer may be halfway through rewriting the last line. Do not parse
  // an unterminated suffix; a complete earlier line remains useful.
  const end = data.lastIndexOf('\n');
  if (end < 0) return fileUnavailable('malformed');
  let events;
  try {
    events = data.slice(0, end).split('\n').map((line) => JSON.parse(line));
  } catch {
    return fileUnavailable('malformed');
  }
  if (!events.length || events.some((event, i) => !validEvent(event, runId)
    || (i > 0 && event.sequence <= events[i - 1].sequence))) return fileUnavailable('malformed');
  const latest = events.at(-1);
  // Persistence is necessary but not sufficient for live trust: only the
  // current child's private monotonic lease, agreeing with the file, grants it.
  const persistedHealth = live ? sampleHealth() : null;
  if (live && (!persistedHealth || persistedHealth.healthy !== true || persistedHealth.sequence !== latest.sequence)) {
    return unavailable('telemetry_unavailable');
  }
  const candidates = events.filter((event) => beforeSequence === undefined || event.sequence < beforeSequence);
  let page = candidates.slice(-limit);
  const reply = () => ({ ...base, availability: 'available', reason: null, events: page,
    next_before_sequence: page.length && candidates[0].sequence < page[0].sequence ? page[0].sequence : null,
    truncated: latest.truncated || candidates.length > page.length,
    last_activity_at: latest.at,
    active_operations: running && currentRunId === runId ? latest.active_operations : [],
    active_truncated: running && currentRunId === runId ? latest.active_truncated : false });
  while (page.length && Buffer.byteLength(JSON.stringify(reply())) > MAX_REPLY_BYTES) page = page.slice(1);
  // Even the fixed fields + one producer event cannot exceed this budget with
  // validated widths; treat any unexpected case as unavailable, never overflow.
  if (Buffer.byteLength(JSON.stringify(reply())) > MAX_REPLY_BYTES) return fileUnavailable('malformed');
  // Sample again after pagination/serialization work, not just after the disk read.
  if (live) {
    const latestHealth = sampleHealth();
    if (!latestHealth || latestHealth.healthy !== true || latestHealth.sequence !== latest.sequence) {
      return unavailable('telemetry_unavailable');
    }
  }
  return reply();
}
