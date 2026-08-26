import { describe, it, expect } from 'vitest';
import { McpClientPool, type ClientConnector, type ConnectedClient, type RawTool } from '../client.js';

/** A network-free fake standing in for the real SDK client. */
function fakeClient(tools: RawTool[]): ConnectedClient {
  return {
    listTools: async () => ({ tools }),
    callTool: async (params) => ({ content: [{ type: 'text', text: `called ${params.name}` }], isError: false }),
    close: async () => {},
  };
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
});
