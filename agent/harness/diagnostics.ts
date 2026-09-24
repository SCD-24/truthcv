/** Privacy-safe, best-effort per-run execution boundaries, separate from the raw event stream. */
import { writeFileSync, unlinkSync } from 'node:fs';
import { Socket } from 'node:net';

export const DIAGNOSTIC_SCHEMA_VERSION = 1;
export const MAX_DIAGNOSTIC_BYTES = 2 * 1024 * 1024;
const MAX_ACTIVE = 128;
export const SAFE_RUN_ID = /^[a-zA-Z0-9_-]{1,80}$/;
export const DIAGNOSTIC_PHASES = ['registry_refresh', 'compaction', 'model', 'tool', 'backoff'] as const;
export type DiagnosticPhase = typeof DIAGNOSTIC_PHASES[number];
export type DiagnosticStatus = 'start' | 'success' | 'error';

/** Only these explicit scalar values may cross the execution/telemetry boundary. */
export interface DiagnosticBoundary {
  operationId: string;
  phase: DiagnosticPhase;
  status: DiagnosticStatus;
  toolName?: string;
  turn?: number;
  retryAttempt?: number;
  delayMs?: number;
}

export interface ActiveOperation {
  operation_id: string;
  phase: DiagnosticPhase;
  started_at: string;
  tool_name?: string;
  turn?: number;
}

export interface DiagnosticsHealth {
  update: (health: 'healthy' | 'unavailable', sequence: number) => void;
  close: () => void;
}

/** The inherited pipe is private and optional. A full pipe drops a frame, never a run turn. */
export function createDiagnosticsHealth(
  fd: number,
  options: {
    transport?: { write: (data: string) => boolean; destroy: () => void; on: (event: string, fn: () => void) => unknown };
    interval?: (fn: () => void, ms: number) => ReturnType<typeof setInterval>;
    clear?: (timer: ReturnType<typeof setInterval>) => void;
  } = {},
): DiagnosticsHealth {
  let transport: NonNullable<typeof options.transport>;
  try { transport = options.transport ?? new Socket({ fd, readable: false, writable: true }); }
  catch { return { update: () => {}, close: () => {} }; }
  let closed = false;
  let busy = false;
  let health: 'healthy' | 'unavailable' | undefined;
  let sequence = 0;
  const fail = () => { closed = true; };
  transport.on('error', fail);
  transport.on('close', fail);
  transport.on('drain', () => { busy = false; });
  const send = () => {
    if (closed || busy || !health) return;
    try { busy = !transport.write(JSON.stringify({ version: 1, health, sequence }) + '\n'); }
    catch { fail(); }
  };
  const timer = (options.interval ?? setInterval)(send, 1000);
  timer.unref?.();
  return {
    update: (state, persisted) => { health = state; sequence = persisted; send(); },
    close: () => { closed = true; (options.clear ?? clearInterval)(timer); try { transport.destroy(); } catch { /* best effort */ } },
  };
}

export interface DiagnosticEvent {
  schema_version: number;
  run_id: string;
  sequence: number;
  at: string;
  operation_id: string;
  phase: DiagnosticPhase;
  status: DiagnosticStatus;
  duration_ms?: number;
  tool_name?: string;
  turn?: number;
  retry_attempt?: number;
  delay_ms?: number;
  active_operations: ActiveOperation[];
  active_truncated: boolean;
  truncated: boolean;
}

/** A failure to write disables diagnostics; it must never change run behavior. */
export function createDiagnostics(
  file: string,
  runId: string,
  options: {
    wall?: () => number;
    monotonic?: () => number;
    write?: (path: string, data: string) => void;
    remove?: (path: string) => void;
    maxBytes?: number;
    health?: DiagnosticsHealth;
  } = {},
): { onDiagnostic: (boundary: DiagnosticBoundary) => void; available: () => boolean } {
  let available = SAFE_RUN_ID.test(runId);
  const wall = options.wall ?? Date.now;
  const monotonic = options.monotonic ?? (() => performance.now());
  const write = options.write ?? ((path: string, data: string) => writeFileSync(path, data, { flag: 'w', mode: 0o600 }));
  const remove = options.remove ?? ((path: string) => unlinkSync(path));
  const active = new Map<string, ActiveOperation & { started_mono: number }>();
  let events: DiagnosticEvent[] = [];
  let sequence = 0;
  let persisted = 0;
  let truncated = false;
  const maxBytes = Math.min(MAX_DIAGNOSTIC_BYTES, Math.max(1024, options.maxBytes ?? MAX_DIAGNOSTIC_BYTES));

  const onDiagnostic = (boundary: DiagnosticBoundary): void => {
    if (!available) return;
    try {
      const now = new Date(wall()).toISOString();
      const mono = monotonic();
      const { operationId, phase, status } = boundary;
      if (!/^[a-z0-9_-]{1,80}$/i.test(operationId) || !DIAGNOSTIC_PHASES.includes(phase) || !['start', 'success', 'error'].includes(status)) return;
      const prior = active.get(operationId);
      const toolName = phase === 'tool' && typeof boundary.toolName === 'string' && /^[a-zA-Z0-9_]{1,80}$/.test(boundary.toolName)
        ? boundary.toolName : phase === 'tool' ? 'unknown' : undefined;
      const event: DiagnosticEvent = { schema_version: DIAGNOSTIC_SCHEMA_VERSION, run_id: runId,
        sequence: ++sequence, at: now, operation_id: operationId, phase, status,
        active_operations: [], active_truncated: false, truncated };
      if (toolName) event.tool_name = toolName;
      if (Number.isSafeInteger(boundary.turn) && boundary.turn! >= 0) event.turn = boundary.turn;
      if (Number.isSafeInteger(boundary.retryAttempt) && boundary.retryAttempt! >= 0) event.retry_attempt = boundary.retryAttempt;
      if (Number.isFinite(boundary.delayMs) && boundary.delayMs! >= 0) event.delay_ms = Math.round(boundary.delayMs!);
      if (status === 'start') active.set(operationId, { operation_id: operationId, phase, started_at: now,
        ...(toolName ? { tool_name: toolName } : {}), ...(event.turn !== undefined ? { turn: event.turn } : {}), started_mono: mono });
      else if (prior) {
        event.duration_ms = Math.max(0, Math.round(mono - prior.started_mono));
        active.delete(operationId);
      }
      const values = [...active.values()];
      event.active_truncated = values.length > MAX_ACTIVE;
      event.active_operations = values.slice(-MAX_ACTIVE).map(({ started_mono: _started, ...op }) => op);
      events.push(event);
      let text = events.map((item) => JSON.stringify(item) + '\n').join('');
      while (Buffer.byteLength(text) > maxBytes && events.length > 1) {
        events.shift();
        truncated = true;
        events.forEach((item) => { item.truncated = true; });
        text = events.map((item) => JSON.stringify(item) + '\n').join('');
      }
      if (Buffer.byteLength(text) > maxBytes) throw new Error('diagnostic event exceeds retention');
      write(file, text);
      persisted = sequence;
      try { options.health?.update('healthy', persisted); } catch { /* the channel must never affect execution */ }
    } catch {
      available = false;
      try { options.health?.update('unavailable', persisted); } catch { /* independent of disk */ }
      try { remove(file); } catch { /* best effort: the private health channel invalidates a stale file */ }
    }
  };
  return { onDiagnostic, available: () => available };
}
