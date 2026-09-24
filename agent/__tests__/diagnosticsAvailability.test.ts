import { describe, it, expect } from 'vitest';
import { EventEmitter, once } from 'node:events';
import net from 'node:net';
// @ts-expect-error standalone JavaScript module intentionally has no declaration file
import { createDiagnosticsAvailability } from '../diagnostics-availability.mjs';

const frame = (health: string, sequence: number) => Buffer.from(JSON.stringify({ version: 1, health, sequence }) + '\n');

function scenario() {
  const pipe = new EventEmitter();
  let now = 0;
  const lease = createDiagnosticsAvailability(pipe, { monotonic: () => now });
  return { pipe, lease, advance: (ms: number) => { now += ms; } };
}

describe('private child-bound health lease', () => {
  it('starts unknown, accepts complete metadata, heartbeats through long waits, expires monotonically', () => {
    const { pipe, lease, advance } = scenario();
    expect(lease.snapshot().healthy).toBe(false);
    const first = frame('healthy', 1);
    pipe.emit('data', first.subarray(0, 8));
    expect(lease.snapshot().healthy).toBe(false);
    pipe.emit('data', first.subarray(8));
    expect(lease.snapshot()).toEqual({ healthy: true, sequence: 1 });
    for (let i = 0; i < 20; i++) {
      advance(1000);
      pipe.emit('data', frame('healthy', 1)); // no new event during a model wait
      expect(lease.snapshot().healthy).toBe(true);
    }
    advance(5001);
    expect(lease.snapshot().healthy).toBe(false);
    pipe.emit('data', frame('healthy', 1));
    expect(lease.snapshot().healthy).toBe(true);
    pipe.emit('end');
    pipe.emit('data', frame('healthy', 2));
    expect(lease.snapshot().healthy).toBe(false);
  });

  it('accepts many coalesced frames and fragmented frames, but rejects one oversized frame', () => {
    const { pipe, lease } = scenario();
    const joined = Buffer.concat(Array.from({ length: 8 }, (_, i) => frame('healthy', i + 1)));
    expect(joined.length).toBeGreaterThan(192);
    pipe.emit('data', joined);
    expect(lease.snapshot()).toEqual({ healthy: true, sequence: 8 });
    const split = frame('healthy', 9);
    for (const byte of split) pipe.emit('data', Buffer.from([byte]));
    expect(lease.snapshot()).toEqual({ healthy: true, sequence: 9 });
    pipe.emit('data', Buffer.concat([frame('healthy', 10), Buffer.alloc(97, 97), Buffer.from('\n')]));
    expect(lease.snapshot().healthy).toBe(false);
    pipe.emit('data', frame('healthy', 11));
    expect(lease.snapshot().healthy).toBe(false);
  });

  it('accepts coalesced transport writes over a real socket', async () => {
    const server = net.createServer();
    server.listen(0, '127.0.0.1');
    await once(server, 'listening');
    const address = server.address() as net.AddressInfo;
    const client = net.connect(address.port, '127.0.0.1');
    try {
      const received = new Promise<{ healthy: boolean; sequence: number }>((resolve) => {
        server.once('connection', (socket) => {
          const lease = createDiagnosticsAvailability(socket);
          socket.on('data', () => {
            const snapshot = lease.snapshot();
            if (snapshot.sequence === 8) resolve(snapshot);
          });
        });
      });
      await once(client, 'connect');
      const payload = Buffer.concat(Array.from({ length: 8 }, (_, i) => frame('healthy', i + 1)));
      expect(payload.length).toBeGreaterThan(192);
      client.write(payload);
      expect(await received).toEqual({ healthy: true, sequence: 8 });
    } finally {
      client.destroy();
      await new Promise<void>((resolve) => server.close(() => resolve()));
    }
  });

  it('fails closed on malformed, oversized, late, downgraded and invalid sequence frames', () => {
    const invalid = [Buffer.from('not json\n'), Buffer.alloc(300, 97),
      Buffer.from('{"version":1,"health":"healthy","sequence":1,"secret":"x"}\n'),
      frame('healthy', 0), frame('unknown', 1), frame('healthy', -1)];
    for (const value of invalid) {
      const { pipe, lease } = scenario();
      pipe.emit('data', value);
      pipe.emit('data', frame('healthy', 1));
      expect(lease.snapshot().healthy).toBe(false);
    }
    const { pipe, lease } = scenario();
    pipe.emit('data', frame('healthy', 2));
    pipe.emit('data', frame('healthy', 1));
    expect(lease.snapshot().healthy).toBe(false);
    const failed = scenario();
    failed.pipe.emit('data', frame('healthy', 1));
    failed.pipe.emit('data', frame('unavailable', 1));
    failed.pipe.emit('data', frame('healthy', 2));
    expect(failed.lease.snapshot().healthy).toBe(false);
  });

  it('invalidates on close, error, cancel and replacement without accepting an old child message', () => {
    const old = scenario();
    old.pipe.emit('data', frame('healthy', 1));
    old.lease.invalidate(); // cancel or replacement
    old.pipe.emit('data', frame('healthy', 2));
    expect(old.lease.snapshot().healthy).toBe(false);
    const next = scenario();
    expect(next.lease.snapshot().healthy).toBe(false);
    next.pipe.emit('data', frame('healthy', 1));
    next.pipe.emit('close');
    expect(next.lease.snapshot().healthy).toBe(false);
    const errored = scenario();
    errored.pipe.emit('error');
    expect(errored.lease.snapshot().healthy).toBe(false);
  });
});
