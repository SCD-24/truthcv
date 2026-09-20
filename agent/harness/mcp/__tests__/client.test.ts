import { describe, it, expect } from 'vitest';
import { Client } from '@modelcontextprotocol/sdk/client/index.js';
import type { Transport } from '@modelcontextprotocol/sdk/shared/transport.js';
import type { JSONRPCMessage, JSONRPCRequest } from '@modelcontextprotocol/sdk/types.js';
import { McpClientPool, type ClientConnector, type ConnectedClient, type RawTool } from '../client.js';

/** A network-free fake standing in for the real SDK client. */
function fakeClient(tools: RawTool[]): ConnectedClient {
  return {
    listTools: async () => ({ tools }),
    callTool: async (params) => ({ content: [{ type: 'text', text: `called ${params.name}` }], isError: false }),
    close: async () => {},
  };
}

/** A promise a test can resolve or reject on its own schedule. */
function deferred<T>(): { promise: Promise<T>; resolve: (v: T) => void; reject: (e: unknown) => void } {
  let resolve!: (v: T) => void;
  let reject!: (e: unknown) => void;
  const promise = new Promise<T>((res, rej) => {
    resolve = res;
    reject = rej;
  });
  return { promise, resolve, reject };
}

describe('McpClientPool', () => {
  it('isolates a failing server and keeps the healthy one usable', async () => {
    const connector: ClientConnector = async (server) => {
      if (server.name === 'bad') throw new Error('boom');
      return fakeClient([{ name: 'do_thing', inputSchema: { type: 'object' } }]);
    };
    const pool = new McpClientPool(
      [{ name: 'good', url: 'http://good' }, { name: 'bad', url: 'http://bad' }],
      connector,
    );
    await pool.connectAll();

    expect(pool.listTools().map((t) => t.namespacedName)).toContain('good__do_thing');
    expect(pool.status('bad')?.status).toBe('errored');
    expect(pool.status('bad')?.lastError).toContain('boom');
    expect(pool.status('good')?.status).toBe('connected');

    const res = await pool.callTool('good__do_thing', {});
    expect(res.isError).toBeFalsy();
    expect(res.content).toContain('called do_thing');
  });

  it('returns an error result when calling a tool whose server is not connected', async () => {
    const connector: ClientConnector = async () => {
      throw new Error('down');
    };
    const pool = new McpClientPool([{ name: 'bad', url: 'http://bad' }], connector);
    await pool.connectAll();

    const res = await pool.callTool('anything__x', {});
    expect(res.isError).toBe(true);
  });

  it('can reconnect a previously failed server and pick up its tools', async () => {
    let failBad = true;
    const connector: ClientConnector = async (server) => {
      if (server.name === 'bad' && failBad) throw new Error('down');
      const toolName = server.name === 'bad' ? 'bad_tool' : 'good_tool';
      return fakeClient([{ name: toolName, inputSchema: { type: 'object' } }]);
    };
    const pool = new McpClientPool(
      [{ name: 'good', url: 'http://good' }, { name: 'bad', url: 'http://bad' }],
      connector,
    );
    await pool.connectAll();

    expect(pool.status('bad')?.status).toBe('errored');
    expect(pool.listTools().map((t) => t.namespacedName)).not.toContain('bad__bad_tool');

    failBad = false;
    await pool.reconnect('bad');

    expect(pool.status('bad')?.status).toBe('connected');
    const names = pool.listTools().map((t) => t.namespacedName);
    expect(names).toContain('bad__bad_tool');
    expect(names).toContain('good__good_tool');

    const res = await pool.callTool('bad__bad_tool', {});
    expect(res.isError).toBeFalsy();
    expect(res.content).toContain('called bad_tool');
  });

  describe('concurrent dispatch safety (markErrored race)', () => {
    it('keeps a concurrent successful call intact when an overlapping call fails, and stays recoverable', async () => {
      const callA = deferred<{ content: unknown; isError?: boolean }>();
      const callB = deferred<{ content: unknown; isError?: boolean }>();
      let calls = 0;
      const client: ConnectedClient = {
        listTools: async () => ({ tools: [{ name: 'do_thing', inputSchema: { type: 'object' } }] }),
        callTool: () => (calls++ === 0 ? callA.promise : callB.promise),
        close: async () => {},
      };
      const connector: ClientConnector = async () => client;
      const pool = new McpClientPool([{ name: 'srv', url: 'http://srv' }], connector);
      await pool.connectAll();

      const a = pool.callTool('srv__do_thing', {});
      const b = pool.callTool('srv__do_thing', {});

      callA.reject(new Error('boom'));
      const resultA = await a;
      expect(resultA.isError).toBe(true);

      callB.resolve({ content: [{ type: 'text', text: 'b ok' }], isError: false });
      const resultB = await b;
      expect(resultB.isError).toBeFalsy();
      expect(resultB.content).toContain('b ok');

      // Not left PERMANENTLY disconnected: the failure marks the entry
      // errored, but it is still reconnectable afterwards.
      expect(pool.status('srv')?.status).toBe('errored');
      await pool.reconnect('srv');
      expect(pool.status('srv')?.status).toBe('connected');
    });

    it('does not let a stale in-flight failure clobber a fresher concurrent reconnect', async () => {
      const staleCall = deferred<{ content: unknown; isError?: boolean }>();
      let connectCount = 0;
      const clientV1: ConnectedClient = {
        listTools: async () => ({ tools: [{ name: 'do_thing', inputSchema: { type: 'object' } }] }),
        callTool: () => staleCall.promise,
        close: async () => {},
      };
      const clientV2: ConnectedClient = {
        listTools: async () => ({ tools: [{ name: 'do_thing', inputSchema: { type: 'object' } }] }),
        callTool: async () => ({ content: [{ type: 'text', text: 'v2 ok' }], isError: false }),
        close: async () => {},
      };
      const connector: ClientConnector = async () => {
        connectCount += 1;
        return connectCount === 1 ? clientV1 : clientV2;
      };
      const pool = new McpClientPool([{ name: 'srv', url: 'http://srv' }], connector);
      await pool.connectAll();

      // A call is dispatched against the CURRENT (v1) client and left
      // in flight — its own generation is captured now, before the reconnect
      // below bumps the entry's generation.
      const inFlight = pool.callTool('srv__do_thing', {});

      // A reconnect races in and succeeds, installing clientV2.
      await pool.reconnect('srv');
      expect(pool.status('srv')?.status).toBe('connected');

      // The stale (v1) call now fails. Its failure belongs to a superseded
      // generation and must be dropped rather than tearing the fresh
      // connection down.
      staleCall.reject(new Error('stale failure'));
      const staleResult = await inFlight;
      expect(staleResult.isError).toBe(true);

      expect(pool.status('srv')?.status).toBe('connected');
      const res = await pool.callTool('srv__do_thing', {});
      expect(res.isError).toBeFalsy();
      expect(res.content).toContain('v2 ok');
    });

    it('coalesces two concurrent reconnect calls for the same server into one connect attempt', async () => {
      let connectCount = 0;
      const gate = deferred<void>();
      const connector: ClientConnector = async () => {
        connectCount += 1;
        await gate.promise;
        return fakeClient([{ name: 'do_thing', inputSchema: { type: 'object' } }]);
      };
      const pool = new McpClientPool([{ name: 'srv', url: 'http://srv' }], connector);

      const first = pool.reconnect('srv');
      const second = pool.reconnect('srv');
      gate.resolve();
      await Promise.all([first, second]);

      expect(connectCount).toBe(1);
      expect(pool.status('srv')?.status).toBe('connected');
    });
  });
});

describe('SDK Client transport multiplexing (verified, not assumed)', () => {
  it('routes out-of-order responses back to the correct concurrent tool call', async () => {
    const sent: JSONRPCMessage[] = [];
    const transport: Transport = {
      start: async () => {},
      send: async (message) => {
        sent.push(message);
      },
      close: async () => {},
    };
    const deliver = (message: JSONRPCMessage): void => transport.onmessage?.(message);
    const byMethod = (method: string): JSONRPCRequest[] =>
      sent.filter((m): m is JSONRPCRequest => (m as { method?: string }).method === method);
    const waitUntil = async (predicate: () => boolean): Promise<void> => {
      for (let i = 0; i < 10_000 && !predicate(); i += 1) await Promise.resolve();
    };

    const client = new Client({ name: 'multiplex-probe', version: '0.0.0' });
    const connecting = client.connect(transport);
    await waitUntil(() => byMethod('initialize').length === 1);
    const initReq = byMethod('initialize')[0];
    const protocolVersion = (initReq.params as { protocolVersion: string }).protocolVersion;
    deliver({
      jsonrpc: '2.0',
      id: initReq.id,
      result: { protocolVersion, capabilities: {}, serverInfo: { name: 'stub-server', version: '0.0.0' } },
    });
    await connecting;

    const callA = client.callTool({ name: 'toolA', arguments: {} });
    const callB = client.callTool({ name: 'toolB', arguments: {} });
    await waitUntil(() => byMethod('tools/call').length === 2);
    const [reqA, reqB] = byMethod('tools/call');
    expect(reqA.id).not.toBe(reqB.id);

    // Deliver B's response first, then A's: if the client did not multiplex
    // (matching responses to requests by id) this would resolve the wrong
    // call with the wrong result.
    deliver({ jsonrpc: '2.0', id: reqB.id, result: { content: [{ type: 'text', text: 'B' }], isError: false } });
    deliver({ jsonrpc: '2.0', id: reqA.id, result: { content: [{ type: 'text', text: 'A' }], isError: false } });

    const [resultA, resultB] = await Promise.all([callA, callB]);
    expect(resultA.content).toEqual([{ type: 'text', text: 'A' }]);
    expect(resultB.content).toEqual([{ type: 'text', text: 'B' }]);
  });
});
