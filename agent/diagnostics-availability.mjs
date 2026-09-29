// Ephemeral, child-bound lease for a private metadata-only pipe. Never persisted.
const MAX_FRAME_BYTES = 96;
const LEASE_MS = 5000;
const HEALTH = new Set(['healthy', 'unavailable']);

/** Parse only complete, bounded frames; a bad frame or closed pipe cannot revive. */
export function createDiagnosticsAvailability(stream, { monotonic = () => performance.now() } = {}) {
  let invalid = false;
  let buffer = Buffer.alloc(0);
  let state = 'unknown';
  let sequence = 0;
  let last = -Infinity;
  const invalidate = () => { invalid = true; state = 'unknown'; buffer = Buffer.alloc(0); };
  stream.on('end', invalidate);
  stream.on('close', invalidate);
  stream.on('error', invalidate);
  stream.on('data', (chunk) => {
    if (invalid || !Buffer.isBuffer(chunk)) return invalidate();
    let start = 0;
    while (start < chunk.length) {
      const end = chunk.indexOf(10, start);
      const length = (end === -1 ? chunk.length : end) - start;
      if (buffer.length + length > MAX_FRAME_BYTES) return invalidate();
      if (end === -1) {
        buffer = Buffer.concat([buffer, chunk.subarray(start)]);
        break;
      }
      if (buffer.length + length === 0) return invalidate();
      const frame = buffer.length ? Buffer.concat([buffer, chunk.subarray(start, end)]) : chunk.subarray(start, end);
      buffer = Buffer.alloc(0);
      start = end + 1;
      let message;
      try { message = JSON.parse(frame.toString('utf8')); }
      catch { return invalidate(); }
      if (!message || Array.isArray(message) || typeof message !== 'object'
        || Object.keys(message).sort().join(',') !== 'health,sequence,version'
        || message.version !== 1 || !HEALTH.has(message.health)
        || !Number.isSafeInteger(message.sequence) || message.sequence < 0
        || (message.health === 'healthy' && message.sequence === 0)
        || message.sequence < sequence || (state === 'unavailable' && message.health === 'healthy')) {
        return invalidate();
      }
      const now = monotonic();
      if (!Number.isFinite(now) || now < last) return invalidate();
      last = now;
      sequence = message.sequence;
      state = message.health;
    }
    if (buffer.length > MAX_FRAME_BYTES) invalidate();
  });
  return {
    invalidate,
    snapshot: () => {
      const now = monotonic();
      return { healthy: !invalid && state === 'healthy' && Number.isFinite(now)
        && now >= last && now - last <= LEASE_MS, sequence };
    },
  };
}
