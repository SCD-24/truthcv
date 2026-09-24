import { describe, it, expect, vi } from 'vitest';
import { createDiagnostics, createDiagnosticsHealth, MAX_DIAGNOSTIC_BYTES, type DiagnosticEvent } from '../diagnostics.js';

const parse = (text: string): DiagnosticEvent[] => text.trim().split('\n').map((line) => JSON.parse(line) as DiagnosticEvent);

describe('safe execution diagnostics', () => {
  it('records fake wall time and monotonic duration without user content or malformed tool names', () => {
    let wall = 1_700_000_000_000;
    let mono = 10;
    let text = '';
    const sink = createDiagnostics('/unused', 'run_1', { wall: () => wall, monotonic: () => mono,
      write: (_path, data) => { text = data; } });
    sink.onDiagnostic({ operationId: 'op_1', phase: 'tool', status: 'start', toolName: 'https://secret.test/key',
      ...({ content: 'secret', arguments: { token: 'secret' }, error: 'secret' } as object) });
    wall += 2000;
    mono += 37;
    sink.onDiagnostic({ operationId: 'op_1', phase: 'tool', status: 'error', toolName: 'https://secret.test/key' });
    const events = parse(text);
    expect(events.map((event) => event.sequence)).toEqual([1, 2]);
    expect(events[0].active_operations[0].tool_name).toBe('unknown');
    expect(events[1].duration_ms).toBe(37);
    expect(events[1].active_operations).toEqual([]);
    expect(events[1].at).toBe(new Date(wall).toISOString());
    expect(text).not.toMatch(/secret|https|token|content|arguments|error.*secret/);
  });

  it('keeps a recent 2MiB window and an active snapshot even when its start is evicted', () => {
    let text = '';
    const sink = createDiagnostics('/unused', 'run_2', { maxBytes: 1024, wall: () => 1000,
      monotonic: () => 1, write: (_path, data) => { text = data; } });
    sink.onDiagnostic({ operationId: 'op_0', phase: 'model', status: 'start' });
    for (let i = 1; i < 30; i++) {
      sink.onDiagnostic({ operationId: `op_${i}`, phase: 'registry_refresh', status: 'start' });
      sink.onDiagnostic({ operationId: `op_${i}`, phase: 'registry_refresh', status: 'success' });
    }
    const events = parse(text);
    expect(Buffer.byteLength(text)).toBeLessThanOrEqual(1024);
    expect(MAX_DIAGNOSTIC_BYTES).toBe(2 * 1024 * 1024);
    expect(events[0].sequence).toBeGreaterThan(1);
    expect(events.at(-1)?.truncated).toBe(true);
    expect(events.at(-1)?.active_operations[0].operation_id).toBe('op_0');
  });

  it('reports failure independently when both overwriting and removing a valid snapshot fail', () => {
    let text = '';
    let writes = 0;
    const frames: string[] = [];
    const health = createDiagnosticsHealth(3, {
      transport: { write: (data) => { frames.push(data); return true; }, destroy: () => {}, on: () => {} },
    });
    const sink = createDiagnostics('/unused', 'run_3', { health,
      write: (_path, data) => { if (++writes === 2) throw Error('secret disk failure'); text = data; },
      remove: () => { throw Error('unlink failed'); },
    });
    sink.onDiagnostic({ operationId: 'op_1', phase: 'model', status: 'start' });
    expect(parse(text).at(-1)?.active_operations).toHaveLength(1);
    sink.onDiagnostic({ operationId: 'op_1', phase: 'model', status: 'success' });
    expect(sink.available()).toBe(false);
    expect(parse(text).at(-1)?.sequence).toBe(1);
    expect(frames.map((line) => JSON.parse(line))).toEqual([
      { version: 1, health: 'healthy', sequence: 1 },
      { version: 1, health: 'unavailable', sequence: 1 },
    ]);
    health.close();
  });

  it('drops frames under backpressure and never blocks persistence or exposes content', () => {
    const frames: string[] = [];
    const handlers: Record<string, () => void> = {};
    let heartbeat = () => {};
    const health = createDiagnosticsHealth(3, {
      transport: { write: (data) => { frames.push(data); return false; }, destroy: () => {},
        on: (event, fn) => { handlers[event] = fn; } },
      interval: (fn) => { heartbeat = fn; return { unref: () => {} } as ReturnType<typeof setInterval>; },
      clear: () => {},
    });
    const sink = createDiagnostics('/unused', 'run_4', { write: () => {}, health });
    sink.onDiagnostic({ operationId: 'op_1', phase: 'model', status: 'start' });
    sink.onDiagnostic({ operationId: 'op_1', phase: 'model', status: 'success' });
    heartbeat();
    expect(frames).toHaveLength(1);
    handlers.drain();
    heartbeat();
    expect(JSON.parse(frames[1])).toEqual({ version: 1, health: 'healthy', sequence: 2 });
    health.close();
  });

  it('disables itself on write failure without throwing or leaving its old file readable', () => {
    const remove = vi.fn();
    const sink = createDiagnostics('/unused', 'run_3', { write: () => { throw Error('secret disk failure'); }, remove });
    expect(() => sink.onDiagnostic({ operationId: 'op_1', phase: 'model', status: 'start' })).not.toThrow();
    expect(sink.available()).toBe(false);
    expect(remove).toHaveBeenCalledOnce();
    sink.onDiagnostic({ operationId: 'op_1', phase: 'model', status: 'success' });
    expect(remove).toHaveBeenCalledOnce();
    expect(createDiagnostics('/unused', '../unsafe').available()).toBe(false);
  });
});
