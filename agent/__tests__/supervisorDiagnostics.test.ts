import { describe, it, expect, vi } from 'vitest';
import fs, { mkdtempSync, readFileSync, writeFileSync, symlinkSync, rmSync, chmodSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join, resolve } from 'node:path';
import { spawn } from 'node:child_process';
import net from 'node:net';
import { EventEmitter, once } from 'node:events';
// @ts-expect-error no declaration file for the standalone .mjs lease
import { createDiagnosticsAvailability } from '../diagnostics-availability.mjs';
import { createDiagnostics } from '../harness/diagnostics.js';
// The supervisor ships this JavaScript file directly rather than building it with tsc.
// @ts-expect-error no declaration file for the standalone .mjs reader
import { readRunDiagnostics } from '../diagnostics.mjs';

function port(): Promise<number> {
  return new Promise((done) => {
    const server = net.createServer();
    server.listen(0, '127.0.0.1', () => {
      const address = server.address() as net.AddressInfo;
      server.close(() => done(address.port));
    });
  });
}

describe('supervisor diagnostics route', () => {
  it('reads only bounded, validated metadata and serves it after the token gate', async () => {
    const dir = mkdtempSync(join(tmpdir(), 'supervisor-diagnostics-'));
    const runId = 'run_test1';
    const file = join(dir, `diagnostics_${runId}.ndjson`);
    const fakeConfig = join(dir, 'config.cjs');
    writeFileSync(fakeConfig, 'process.stdout.write(process.argv[2] === "enabled" ? "false" : "");');
    const sink = createDiagnostics(file, runId, { wall: () => 1_700_000_000_000, monotonic: () => 17 });
    sink.onDiagnostic({ operationId: 'op_1', phase: 'model', status: 'start' });
    sink.onDiagnostic({ operationId: 'op_1', phase: 'model', status: 'success' });
    sink.onDiagnostic({ operationId: 'op_2', phase: 'tool', status: 'start', toolName: 'unknown' });
    const produced = readRunDiagnostics(dir, runId, { running: true, currentRunId: runId,
      health: { healthy: true, sequence: 3 } });
    expect(produced.availability).toBe('available');
    expect(produced.events.map((e: { sequence: number }) => e.sequence)).toEqual([1, 2, 3]);
    expect(produced.active_operations[0].operation_id).toBe('op_2');
    expect(readRunDiagnostics(dir, runId).active_operations).toEqual([]); // historical != executing
    expect(readRunDiagnostics(dir, runId, { limit: 1 }).next_before_sequence).toBe(3);
    expect(readRunDiagnostics(dir, runId, { beforeSequence: 3, limit: 1 }).events[0].sequence).toBe(2);
    expect(readRunDiagnostics(dir, 'legacy').reason).toBe('missing');

    // A trailing partial write is ignored; an interior bad line or an
    // unexpected field is rejected rather than echoed back to a caller.
    const valid = readFileSync(file, 'utf8');
    writeFileSync(file, valid + '{"content":"secret');
    expect(readRunDiagnostics(dir, runId).events).toHaveLength(3);
    writeFileSync(file, valid.replace('"status":"start"', '"status":"start","content":"secret"'));
    expect(readRunDiagnostics(dir, runId).reason).toBe('malformed');
    writeFileSync(file, valid);
    symlinkSync(file, join(dir, 'diagnostics_link.ndjson'));
    expect(readRunDiagnostics(dir, 'link').availability).toBe('unavailable');
    writeFileSync(join(dir, 'diagnostics_large.ndjson'), 'x'.repeat(2 * 1024 * 1024 + 1));
    expect(readRunDiagnostics(dir, 'large').availability).toBe('unavailable');
    expect(() => readRunDiagnostics(dir, '../escape')).toThrow(RangeError);

    const busyId = 'busy';
    const busy = createDiagnostics(join(dir, `diagnostics_${busyId}.ndjson`), busyId,
      { wall: () => 1_700_000_000_000, monotonic: () => 17 });
    for (let i = 0; i < 80; i++) {
      busy.onDiagnostic({ operationId: `op_${i}`, phase: 'tool', status: 'start', toolName: 'check_cooldown' });
    }
    const bounded = readRunDiagnostics(dir, busyId, { limit: 200, running: true, currentRunId: busyId,
      health: { healthy: true, sequence: 80 } });
    expect(Buffer.byteLength(JSON.stringify(bounded))).toBeLessThanOrEqual(256 * 1024);
    expect(bounded.next_before_sequence).not.toBeNull();
    expect(bounded.events.at(-1).sequence).toBe(80);

    const controlPort = await port();
    const child = spawn(process.execPath, [resolve(__dirname, '../supervisor.js')], {
      env: { ...process.env, AGENT_API_TOKEN: 'test-secret', AGENT_CONTROL_PORT: String(controlPort),
        RUN_LOG_DIR: dir, AGENT_CONFIG_JS: fakeConfig, RUN_AT: '09:00', RUN_DAYS: '1', TZ: 'UTC' },
      stdio: 'ignore',
    });
    const base = `http://127.0.0.1:${controlPort}`;
    const request = (url: string, token = 'test-secret') => fetch(base + url, { headers: { 'X-Agent-Token': token } });
    try {
      let ready = false;
      for (let i = 0; i < 100; i++) {
        try { if ((await request('/status')).ok) { ready = true; break; } } catch { /* starting */ }
        await new Promise((done) => setTimeout(done, 50));
      }
      expect(ready).toBe(true);
      const endpoint = `/diagnostics/runs/${runId}/events`;
      expect((await request(endpoint, 'wrong')).status).toBe(403);
      const response = await request(endpoint + '?limit=1');
      expect(response.status).toBe(200);
      const body = await response.json();
      expect(body).toMatchObject({ schema_version: 1, run_id: runId, availability: 'available',
        running: false, currentRunId: null, next_before_sequence: 3 });
      expect(body.events.map((e: { sequence: number }) => e.sequence)).toEqual([3]);
      expect(body.active_operations).toEqual([]);
      expect(response.headers.get('content-length')).toBeTruthy();
      expect((await request('/diagnostics/runs/legacy/events')).status).toBe(200);
      expect((await request('/diagnostics/runs/legacy/events').then((r) => r.json())).reason).toBe('missing');
      for (const url of [endpoint + '?limit=0', endpoint + '?limit=201', endpoint + '?limit=1.5',
        endpoint + '?before_sequence=Infinity', endpoint + '?before_sequence=-1',
        endpoint + '?limit=1&limit=2', '/diagnostics/runs/..%2Fescape/events']) {
        expect((await request(url)).status).toBe(400);
      }
      expect((await request('/status').then((r) => r.json())).running).toBe(false);
      expect((await fetch(base + '/cancel', { method: 'POST', headers: { 'X-Agent-Token': 'test-secret' } })
        .then((r) => r.json())).cancelled).toBe(false);
    } finally {
      if (child.exitCode === null) {
        child.kill('SIGTERM');
        await once(child, 'exit');
      }
      rmSync(dir, { recursive: true, force: true });
    }
  }, 15_000);

  it('samples the current lease after synchronous disk IO, not just before it', () => {
    const dir = mkdtempSync(join(tmpdir(), 'diagnostics-lease-expiry-'));
    const runId = 'expiry';
    let now = 0;
    const pipe = new EventEmitter();
    const lease = createDiagnosticsAvailability(pipe, { monotonic: () => now });
    const originalRead = fs.readSync;
    try {
      const sink = createDiagnostics(join(dir, `diagnostics_${runId}.ndjson`), runId);
      sink.onDiagnostic({ operationId: 'op_1', phase: 'model', status: 'start' });
      pipe.emit('data', Buffer.from(JSON.stringify({ version: 1, health: 'healthy', sequence: 1 }) + '\n'));
      const read = vi.spyOn(fs, 'readSync').mockImplementation((fd, buffer, offset, length, position) => {
        now += 5001;
        return originalRead(fd, buffer, offset, length, position);
      });
      try {
        expect(readRunDiagnostics(dir, runId, { running: true, currentRunId: runId,
          health: () => lease.snapshot() })).toMatchObject({ availability: 'unavailable',
            reason: 'telemetry_unavailable', events: [], active_operations: [] });
        expect(read).toHaveBeenCalled();
      } finally { read.mockRestore(); }
      expect(readRunDiagnostics(dir, runId).availability).toBe('available');
    } finally { rmSync(dir, { recursive: true, force: true }); }
  });

  it('does not trust a valid stale snapshot when writing and unlinking both fail', () => {
    const dir = mkdtempSync(join(tmpdir(), 'diagnostics-stale-'));
    const runId = 'stale';
    const file = join(dir, `diagnostics_${runId}.ndjson`);
    let writes = 0;
    let health: { healthy: boolean; sequence: number } = { healthy: false, sequence: 0 };
    try {
      const sink = createDiagnostics(file, runId, {
        write: (dest, text) => { if (++writes === 2) throw Error('disk failed'); writeFileSync(dest, text); },
        remove: () => { throw Error('unlink failed'); },
        health: { update: (state, sequence) => { health = { healthy: state === 'healthy', sequence }; }, close: () => {} },
      });
      sink.onDiagnostic({ operationId: 'op_1', phase: 'model', status: 'start' });
      expect(readRunDiagnostics(dir, runId, { running: true, currentRunId: runId, health }).active_operations).toHaveLength(1);
      sink.onDiagnostic({ operationId: 'op_1', phase: 'model', status: 'success' });
      expect(readFileSync(file, 'utf8')).toContain('"status":"start"');
      expect(readRunDiagnostics(dir, runId, { running: true, currentRunId: runId, health }))
        .toMatchObject({ running: true, currentRunId: runId, availability: 'unavailable',
          reason: 'telemetry_unavailable', events: [], active_operations: [] });
      expect(readRunDiagnostics(dir, runId).events).toHaveLength(1);
      expect(readRunDiagnostics(dir, runId, { running: true, currentRunId: runId,
        health: { healthy: true, sequence: 2 } }).reason).toBe('telemetry_unavailable');
      writeFileSync(file, '{"secret":"bad"}\n');
      expect(readRunDiagnostics(dir, runId, { running: true, currentRunId: runId,
        health: () => health }).reason).toBe('telemetry_unavailable');
      expect(readRunDiagnostics(dir, runId, { running: true, currentRunId: runId,
        health: { healthy: true, sequence: 1 } }).reason).toBe('malformed');
    } finally { rmSync(dir, { recursive: true, force: true }); }
  });

  it('reports failed writes that truncate disk as telemetry loss when unlink also fails', () => {
    const dir = mkdtempSync(join(tmpdir(), 'diagnostics-truncated-'));
    const runId = 'truncated';
    const file = join(dir, `diagnostics_${runId}.ndjson`);
    let writes = 0;
    let health = { healthy: false, sequence: 0 };
    try {
      const sink = createDiagnostics(file, runId, {
        write: (dest, text) => {
          if (++writes === 2) { writeFileSync(dest, '{"secret":"partial'); throw Error('disk failed'); }
          writeFileSync(dest, text);
        },
        remove: () => { throw Error('unlink failed'); },
        health: { update: (state, sequence) => { health = { healthy: state === 'healthy', sequence }; }, close: () => {} },
      });
      sink.onDiagnostic({ operationId: 'op_1', phase: 'model', status: 'start' });
      sink.onDiagnostic({ operationId: 'op_1', phase: 'model', status: 'success' });
      expect(readFileSync(file, 'utf8')).toBe('{"secret":"partial');
      expect(readRunDiagnostics(dir, runId, { running: true, currentRunId: runId,
        health: () => health })).toMatchObject({ running: true, currentRunId: runId,
          availability: 'unavailable', reason: 'telemetry_unavailable', events: [], active_operations: [] });
      expect(readRunDiagnostics(dir, runId).reason).toBe('malformed');
      expect(readRunDiagnostics(dir, runId, { running: true, currentRunId: 'other',
        health: () => health }).reason).toBe('malformed');
      expect(readRunDiagnostics(dir, runId, { running: true, currentRunId: runId,
        health: { healthy: true, sequence: 1 } }).reason).toBe('malformed');
    } finally { rmSync(dir, { recursive: true, force: true }); }
  });

  it('binds live trust to the current child and invalidates it on cancellation', async () => {
    const dir = mkdtempSync(join(tmpdir(), 'supervisor-health-'));
    const fakeConfig = join(dir, 'config.cjs');
    const fakeChild = join(dir, 'fake-child.cjs');
    writeFileSync(fakeConfig, 'process.stdout.write(process.argv[2] === "enabled" ? "false" : "");');
    writeFileSync(fakeChild, `#!${process.execPath}\nconst fs = require('node:fs');\nconst path = require('node:path');\nconst id = process.env.TRUTHCV_RUN_ID;\nconst at = '2023-11-14T22:13:20.000Z';\nconst op = {operation_id:'op_1',phase:'model',started_at:at};\nconst event = {schema_version:1,run_id:id,sequence:1,at,operation_id:'op_1',phase:'model',status:'start',active_operations:[op],active_truncated:false,truncated:false};\nfs.writeFileSync(path.join(process.env.RUN_LOG_DIR, 'diagnostics_' + id + '.ndjson'), JSON.stringify(event) + '\\n');\nfs.writeSync(3, JSON.stringify({version:1,health:'healthy',sequence:1}) + '\\n');\nsetInterval(() => { try { fs.writeSync(3, JSON.stringify({version:1,health:'healthy',sequence:1}) + '\\n'); } catch {} }, 1000);\nprocess.on('SIGTERM', () => process.exit(0));\n`);
    chmodSync(fakeChild, 0o700);
    const controlPort = await port();
    const child = spawn(process.execPath, [resolve(__dirname, '../supervisor.js')], {
      env: { ...process.env, AGENT_API_TOKEN: 'test-secret', AGENT_CONTROL_PORT: String(controlPort),
        RUN_LOG_DIR: dir, DAILY_APPLY: fakeChild, TRUTHCV_MCP_URL: '', AGENT_CONFIG_JS: fakeConfig,
        RUN_AT: '09:00', RUN_DAYS: '1', TZ: 'UTC' }, stdio: 'ignore',
    });
    const base = `http://127.0.0.1:${controlPort}`;
    const request = (url: string, method = 'GET') => fetch(base + url,
      { method, headers: { 'X-Agent-Token': 'test-secret' } }).then((reply) => reply.json());
    try {
      for (let i = 0; i < 100; i++) {
        try { await request('/status'); break; } catch { await new Promise((done) => setTimeout(done, 25)); }
      }
      expect((await request('/run', 'POST')).started).toBe(true);
      const id = (await request('/status')).currentRunId;
      expect(typeof id).toBe('string');
      const url = `/diagnostics/runs/${id}/events`;
      let live;
      for (let i = 0; i < 100; i++) {
        live = await request(url);
        if (live.availability === 'available') break;
        await new Promise((done) => setTimeout(done, 25));
      }
      expect(live).toMatchObject({ availability: 'available', running: true, currentRunId: id });
      expect(live.active_operations).toHaveLength(1);
      expect((await request('/cancel', 'POST')).cancelled).toBe(true);
      expect(await request(url)).toMatchObject({ availability: 'unavailable',
        reason: 'telemetry_unavailable', running: true, currentRunId: id, events: [], active_operations: [] });
      for (let i = 0; i < 100 && (await request('/status')).running; i++) {
        await new Promise((done) => setTimeout(done, 25));
      }
      expect(await request(url)).toMatchObject({ availability: 'available', running: false,
        active_operations: [] });
    } finally {
      if (child.exitCode === null) { child.kill('SIGTERM'); await once(child, 'exit'); }
      rmSync(dir, { recursive: true, force: true });
    }
  }, 15_000);

  it('rejects coerced IDs and tool names without echoing malformed metadata', () => {
    const dir = mkdtempSync(join(tmpdir(), 'diagnostics-invalid-'));
    const runId = 'run_test1';
    const file = join(dir, `diagnostics_${runId}.ndjson`);
    try {
      const sink = createDiagnostics(file, runId, { wall: () => 1_700_000_000_000 });
      sink.onDiagnostic({ operationId: 'op_1', phase: 'tool', status: 'start', toolName: 'unknown' });
      const valid = JSON.parse(readFileSync(file, 'utf8').trim());
      for (const [field, value] of [
        ['operation_id', ['op_1']], ['operation_id', { secret: 'op_1' }],
        ['tool_name', ['unknown']], ['tool_name', null],
      ] as const) {
        const event = { ...valid, [field]: value };
        writeFileSync(file, JSON.stringify(event) + '\n');
        const result = readRunDiagnostics(dir, runId);
        expect(result.reason).toBe('malformed');
        expect(JSON.stringify(result)).not.toContain('secret');
      }
      for (const [field, value] of [
        ['operation_id', ['op_1']], ['operation_id', null],
        ['tool_name', ['unknown']], ['tool_name', { secret: 'unknown' }],
      ] as const) {
        const event = { ...valid, active_operations: [{ ...valid.active_operations[0], [field]: value }] };
        writeFileSync(file, JSON.stringify(event) + '\n');
        const result = readRunDiagnostics(dir, runId);
        expect(result.reason).toBe('malformed');
        expect(JSON.stringify(result)).not.toContain('secret');
      }
      for (const invalid of [[runId], null, { secret: runId }]) {
        expect(() => readRunDiagnostics(dir, invalid)).toThrow(RangeError);
      }
    } finally {
      rmSync(dir, { recursive: true, force: true });
    }
  });

  it('reports a truncated live snapshot even when the requested event page is empty', () => {
    const dir = mkdtempSync(join(tmpdir(), 'diagnostics-active-'));
    const runId = 'run_active';
    try {
      const sink = createDiagnostics(join(dir, `diagnostics_${runId}.ndjson`), runId,
        { wall: () => 1_700_000_000_000, monotonic: () => 17 });
      for (let i = 0; i < 129; i++) {
        sink.onDiagnostic({ operationId: `op_${i}`, phase: 'tool', status: 'start', toolName: 'unknown' });
      }
      const latest = readRunDiagnostics(dir, runId, { limit: 1, beforeSequence: 1,
        running: true, currentRunId: runId, health: { healthy: true, sequence: 129 } });
      expect(latest.availability).toBe('available');
      expect(latest.events).toEqual([]);
      expect(latest.active_operations).toHaveLength(128);
      expect(latest.active_truncated).toBe(true);
      expect(readRunDiagnostics(dir, runId, { running: false, currentRunId: runId }).active_truncated).toBe(false);
      expect(readRunDiagnostics(dir, runId, { running: true, currentRunId: 'other' }).active_truncated).toBe(false);
      expect(readRunDiagnostics(dir, 'missing', { running: true, currentRunId: 'missing' }).active_truncated).toBe(false);
    } finally {
      rmSync(dir, { recursive: true, force: true });
    }
  });
});
