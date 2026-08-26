import type { McpServerConfig } from './config.js';
import { namespaceTools, type ToolRef } from './nameTransform.js';

/** Connection state of a pooled MCP server. */
export type ServerStatus = 'connected' | 'errored';

/**
 * A tool as reported by a server's `tools/list`, before namespacing.
 */
export interface RawTool {
  /** The tool's own name. */
  name: string;
  /** Human-readable description, if the server supplied one. */
  description?: string;
  /** The tool's JSON Schema input definition. */
  inputSchema: Record<string, unknown>;
}

/**
 * A tool exposed by the pool under its collision-free namespaced name.
 */
export interface NamespacedTool {
  /** The unique namespaced name callers use with {@link McpClientPool.callTool}. */
  namespacedName: string;
  /** The server that owns the tool. */
  serverName: string;
  /** The tool's own (un-namespaced) name. */
  toolName: string;
  /** Human-readable description ("" if none was reported). */
  description: string;
  /** The tool's JSON Schema input definition. */
  inputSchema: Record<string, unknown>;
}

/** The flattened result of invoking a tool. */
export interface ToolCallResult {
  /** Tool output rendered to a string. */
  content: string;
  /** True when the call failed or the server reported an error. */
  isError?: boolean;
}

/**
 * The minimal MCP client surface the pool depends on.
 *
 * The real `@modelcontextprotocol/sdk` `Client` is adapted to this shape by the
 * default connector; tests inject a fake that implements it, so no network is
 * required.
 */
export interface ConnectedClient {
  /** List the server's tools via `tools/list`. */
  listTools(): Promise<{ tools: RawTool[] }>;
  /** Invoke a tool by its own name. */
  callTool(params: { name: string; arguments?: Record<string, unknown> }): Promise<{ content: unknown; isError?: boolean }>;
  /** Close the underlying transport. */
  close(): Promise<void>;
}

/**
 * Factory that connects to one server and returns a ready {@link ConnectedClient}.
 * Injected in tests; defaults to a real streamable-HTTP SDK client.
 */
export type ClientConnector = (server: McpServerConfig) => Promise<ConnectedClient>;

interface ServerEntry {
  name: string;
  url: string;
  status: ServerStatus;
  client?: ConnectedClient;
  rawTools: RawTool[];
  lastError?: string;
}

/**
 * A pool of MCP servers connected over streamable HTTP.
 *
 * Each server connects independently: a failure isolates that server (recorded
 * as `errored` and retryable via {@link reconnect}) without preventing the
 * others from being listed and called. Tools from all connected servers are
 * exposed under collision-free namespaced names.
 */
export class McpClientPool {
  private readonly servers = new Map<string, ServerEntry>();
  private readonly connect: ClientConnector;
  private toolIndex = new Map<string, NamespacedTool>();

  /**
   * @param servers The servers to manage.
   * @param connector How to connect to a server; defaults to the real SDK.
   */
  constructor(servers: McpServerConfig[], connector: ClientConnector = defaultConnector) {
    this.connect = connector;
    for (const s of servers) {
      this.servers.set(s.name, { name: s.name, url: s.url, status: 'errored', rawTools: [] });
    }
  }

  /** Connect to every server independently, then build the tool index. */
  async connectAll(): Promise<void> {
    await Promise.all([...this.servers.values()].map((e) => this.connectOne(e)));
    this.rebuildIndex();
  }

  /** All currently-available namespaced tools across connected servers. */
  listTools(): NamespacedTool[] {
    return [...this.toolIndex.values()];
  }

  /**
   * Call a namespaced tool, dispatching to its owning server. Returns an
   * `isError` result (rather than throwing) when the tool is unknown or its
   * server is disconnected, leaving the server retryable via {@link reconnect}.
   */
  async callTool(namespacedName: string, args: Record<string, unknown>): Promise<ToolCallResult> {
    const target = this.toolIndex.get(namespacedName);
    if (!target) return { content: `Unknown tool: ${namespacedName}`, isError: true };
    const entry = this.servers.get(target.serverName);
    if (!entry || entry.status !== 'connected' || !entry.client) {
      return { content: `MCP server '${target.serverName}' is not connected${reason(entry)}`, isError: true };
    }
    return this.dispatch(entry, target.toolName, args);
  }

  /** Retry connecting one named server and, on success, refresh its tools. */
  async reconnect(name: string): Promise<void> {
    const entry = this.servers.get(name);
    if (!entry) throw new Error(`Unknown MCP server: ${name}`);
    await this.connectOne(entry);
    this.rebuildIndex();
  }

  /** Re-list tools from all connected servers and rebuild the tool index. */
  async refreshTools(): Promise<void> {
    await Promise.all(this.connectedEntries().map((e) => this.relistTools(e)));
    this.rebuildIndex();
  }

  /** Current status snapshot for one server, or undefined if unknown. */
  status(name: string): { name: string; status: ServerStatus; lastError?: string } | undefined {
    const entry = this.servers.get(name);
    return entry ? { name: entry.name, status: entry.status, lastError: entry.lastError } : undefined;
  }

  private async connectOne(entry: ServerEntry): Promise<void> {
    try {
      const client = await this.connect({ name: entry.name, url: entry.url });
      entry.client = client;
      entry.status = 'connected';
      entry.lastError = undefined;
      entry.rawTools = (await client.listTools()).tools;
    } catch (err) {
      this.markErrored(entry, err);
    }
  }

  private async relistTools(entry: ServerEntry): Promise<void> {
    try {
      entry.rawTools = (await entry.client!.listTools()).tools;
    } catch (err) {
      this.markErrored(entry, err);
    }
  }

  private async dispatch(entry: ServerEntry, toolName: string, args: Record<string, unknown>): Promise<ToolCallResult> {
    try {
      const res = await entry.client!.callTool({ name: toolName, arguments: args });
      return { content: stringifyContent(res.content), isError: res.isError };
    } catch (err) {
      this.markErrored(entry, err);
      return { content: errorMessage(err), isError: true };
    }
  }

  private markErrored(entry: ServerEntry, err: unknown): void {
    entry.status = 'errored';
    entry.lastError = errorMessage(err);
    entry.client = undefined;
    entry.rawTools = [];
  }

  private connectedEntries(): ServerEntry[] {
    return [...this.servers.values()].filter((e) => e.status === 'connected' && e.client);
  }

  private rebuildIndex(): void {
    const index = new Map<string, NamespacedTool>();
    for (const [namespacedName, ref] of namespaceTools(this.collectPairs())) {
      index.set(namespacedName, this.toNamespacedTool(namespacedName, ref));
    }
    this.toolIndex = index;
  }

  private collectPairs(): ToolRef[] {
    const pairs: ToolRef[] = [];
    for (const entry of this.connectedEntries()) {
      for (const tool of entry.rawTools) pairs.push({ serverName: entry.name, toolName: tool.name });
    }
    return pairs;
  }

  private toNamespacedTool(namespacedName: string, ref: ToolRef): NamespacedTool {
    const raw = this.servers.get(ref.serverName)?.rawTools.find((t) => t.name === ref.toolName);
    return {
      namespacedName,
      serverName: ref.serverName,
      toolName: ref.toolName,
      description: raw?.description ?? '',
      inputSchema: raw?.inputSchema ?? {},
    };
  }
}

/**
 * Construct a pool and connect all its servers in one call.
 *
 * @param servers The servers to manage.
 * @param connector Optional connector override (for tests).
 * @returns A pool whose {@link McpClientPool.connectAll} has already run.
 */
export async function createMcpClientPool(
  servers: McpServerConfig[],
  connector?: ClientConnector,
): Promise<McpClientPool> {
  const pool = new McpClientPool(servers, connector);
  await pool.connectAll();
  return pool;
}

/** Default connector: real SDK Client over streamable HTTP, adapted to ConnectedClient. */
async function defaultConnector(server: McpServerConfig): Promise<ConnectedClient> {
  const { Client } = await import('@modelcontextprotocol/sdk/client/index.js');
  const { StreamableHTTPClientTransport } = await import('@modelcontextprotocol/sdk/client/streamableHttp.js');
  const client = new Client({ name: 'truthcv-harness', version: '0.0.0' });
  await client.connect(new StreamableHTTPClientTransport(new URL(server.url)));
  return {
    listTools: async () => ({ tools: (await client.listTools()).tools.map(toRawTool) }),
    callTool: async (params) => adaptCallResult(await client.callTool(params)),
    close: () => client.close(),
  };
}

/** Narrow one SDK tool descriptor to the fields the pool needs. */
function toRawTool(tool: { name: string; description?: string; inputSchema: Record<string, unknown> }): RawTool {
  return { name: tool.name, description: tool.description, inputSchema: tool.inputSchema };
}

/** Extract content/isError from an SDK callTool result union. */
function adaptCallResult(res: unknown): { content: unknown; isError?: boolean } {
  if (!isRecord(res)) return { content: undefined };
  return { content: res.content, isError: typeof res.isError === 'boolean' ? res.isError : undefined };
}

/** Render MCP content blocks (or arbitrary content) to a single string. */
function stringifyContent(content: unknown): string {
  if (!Array.isArray(content)) return typeof content === 'string' ? content : JSON.stringify(content ?? '');
  return content.map(blockToText).join('');
}

/** Render one content block: its text if it is a text block, else JSON. */
function blockToText(block: unknown): string {
  if (isRecord(block) && typeof block.text === 'string') return block.text;
  return JSON.stringify(block);
}

/** Reason suffix for a disconnected-server error message. */
function reason(entry: ServerEntry | undefined): string {
  return entry?.lastError ? `: ${entry.lastError}` : '';
}

/** Coerce an unknown thrown value into a message string. */
function errorMessage(err: unknown): string {
  return err instanceof Error ? err.message : String(err);
}

/** Type guard for a plain object. */
function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null;
}
