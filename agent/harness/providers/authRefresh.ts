/**
 * Mid-run recovery from a 401 on a subscription OAuth token.
 *
 * When claude/codex OAuth credentials are rejected, the app can mint a fresh
 * token (`POST /api/agent/llm-token/refresh`). This module wraps a provider
 * adapter so the first 401 triggers one refresh and one retry; every other
 * outcome passes through untouched. Tokens are never put in messages or logs.
 */

import { createHash } from 'node:crypto';
import { createProviderAdapter, type Provider, type ProviderAdapterOptions } from './registry.js';
import type { HarnessEvent, ModelRequest, ProviderAdapter } from './types.js';

/** Path of the app's token-refresh route, relative to the app base URL. */
const REFRESH_PATH = '/api/agent/llm-token/refresh';
/** Max time to wait for the app's refresh endpoint. */
const REFRESH_TIMEOUT_MS = 15_000;
/** HTTP status of a successful refresh. */
const HTTP_OK = 200;
/** Matches the status text emitted by `providerErrorEvent` for a 401. */
const STATUS_401 = /\bstatus 401\b/;
/** Providers whose OAuth tokens the app can refresh. */
const REFRESHABLE: readonly Provider[] = ['claude', 'codex'];
/** Vendor display names for the reconnect message. */
const SUBSCRIPTION_LABELS: Partial<Record<Provider, string>> = { claude: 'Claude', codex: 'ChatGPT' };

/** Asks the app for a replacement token after one was rejected. */
export interface TokenRefresher {
  /** Resolve a fresh token for `provider`, given the rejected one; throws on failure. */
  refresh(provider: Provider, rejectedToken: string): Promise<string>;
}

/** Options for {@link createAppTokenRefresher}. */
export interface AppTokenRefresherOptions {
  /** App base URL with no trailing `/mcp`. */
  appBaseUrl: string;
  /** Agent token sent as `X-Agent-Token`. */
  agentToken: string;
  /** Fetch implementation; defaults to global fetch. */
  fetchFn?: typeof fetch;
  /** Called with each newly issued token (e.g. to register it for redaction). */
  onNewToken?: (token: string) => void;
}

/** Hex SHA-256 of a token: identifies it to the app without revealing it. */
function sha256Hex(token: string): string {
  return createHash('sha256').update(token).digest('hex');
}

/** Pull the server's `detail` from a failed response, or '' when absent. */
async function readDetail(res: Response): Promise<string> {
  try {
    const body = (await res.json()) as { detail?: unknown };
    return typeof body?.detail === 'string' ? body.detail : '';
  } catch {
    return '';
  }
}

/** Perform one refresh request and return the new token. */
async function requestToken(
  o: AppTokenRefresherOptions,
  provider: Provider,
  rejectedToken: string,
): Promise<string> {
  const doFetch = o.fetchFn ?? fetch;
  let res: Response;
  try {
    res = await doFetch(`${o.appBaseUrl}${REFRESH_PATH}`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', 'X-Agent-Token': o.agentToken },
      body: JSON.stringify({ provider, rejectedTokenSha256: sha256Hex(rejectedToken) }),
      signal: AbortSignal.timeout(REFRESH_TIMEOUT_MS),
    });
  } catch {
    throw new Error('token refresh request failed or timed out');
  }
  if (res.status !== HTTP_OK) {
    const detail = await readDetail(res);
    throw new Error(`token refresh failed with status ${res.status}${detail ? `: ${detail}` : ''}`);
  }
  const { token } = (await res.json()) as { token?: unknown };
  if (typeof token !== 'string' || !token) throw new Error('token refresh returned no token');
  return token;
}

/**
 * Build a refresher that calls the app, coalescing concurrent calls for the
 * same provider into one request (single-flight).
 */
export function createAppTokenRefresher(o: AppTokenRefresherOptions): TokenRefresher {
  const inFlight = new Map<Provider, Promise<string>>();
  return {
    refresh(provider, rejectedToken) {
      const existing = inFlight.get(provider);
      if (existing) return existing;
      const pending = requestToken(o, provider, rejectedToken).then((token) => {
        o.onNewToken?.(token);
        return token;
      });
      inFlight.set(provider, pending);
      const clear = (): void => void inFlight.delete(provider);
      pending.then(clear, clear);
      return pending;
    },
  };
}

/** Whether these options describe a refreshable subscription token. */
function isRefreshable(opts: ProviderAdapterOptions): boolean {
  return opts.authType === 'oauth' && REFRESHABLE.includes(opts.provider);
}

/** The error event shown when the token was rejected and could not be renewed. */
function reconnectEvent(provider: Provider, reason: string): HarnessEvent {
  const vendor = SUBSCRIPTION_LABELS[provider] ?? provider;
  const base =
    `${vendor} subscription token was rejected (401) and could not be refreshed — ` +
    `reconnect the ${vendor} subscription in Settings (Model routing → Accounts)`;
  return { type: 'error', retryable: false, message: reason ? `${base} (${reason})` : base };
}

/** Whether an event is a 401 provider error. */
function is401(event: HarnessEvent): boolean {
  return event.type === 'error' && STATUS_401.test(event.message);
}

/** Describe a thrown refresh failure without any token. */
function reasonOf(err: unknown): string {
  return err instanceof Error ? err.message : String(err);
}

/** Mutable adapter state shared by all requests through one wrapper. */
interface RefreshState {
  current: ProviderAdapterOptions;
  adapter: ProviderAdapter;
}

/**
 * Rebuild the adapter after a 401 on token `used`. If another request already
 * replaced the token, reuse it without calling the refresher. Returns a
 * reconnect error event on failure, otherwise undefined.
 */
async function refreshAndRebuild(
  state: RefreshState,
  used: string,
  build: (opts: ProviderAdapterOptions) => ProviderAdapter,
  refresher: TokenRefresher,
): Promise<HarnessEvent | undefined> {
  try {
    const token = state.current.token !== used ? state.current.token : await refresher.refresh(state.current.provider, used);
    state.current = { ...state.current, token };
    state.adapter = build(state.current);
    return undefined;
  } catch (err) {
    return reconnectEvent(state.current.provider, reasonOf(err));
  }
}

/**
 * Wrap an adapter so a first-event 401 triggers one refresh and one retry.
 *
 * Pass-through unless the options are claude/codex OAuth. The refreshed token
 * is kept for later calls.
 */
export function withAuthRefresh(
  opts: ProviderAdapterOptions,
  build: (opts: ProviderAdapterOptions) => ProviderAdapter,
  refresher: TokenRefresher,
): ProviderAdapter {
  if (!isRefreshable(opts)) return build(opts);
  const state: RefreshState = { current: opts, adapter: build(opts) };
  return {
    async *sendMessage(request: ModelRequest) {
      const used = state.current.token;
      const first = await firstEvent(state.adapter.sendMessage(request));
      if (!first.event || !is401(first.event)) {
        yield* first.replay();
        return;
      }
      const failure = await refreshAndRebuild(state, used, build, refresher);
      if (failure) {
        yield failure;
        return;
      }
      yield* retryOnce(state, request);
    },
  };
}

/** Re-send a request once on the rebuilt adapter; a second 401 becomes the reconnect error. */
async function* retryOnce(state: RefreshState, request: ModelRequest): AsyncGenerator<HarnessEvent, void, unknown> {
  const retry = await firstEvent(state.adapter.sendMessage(request));
  if (retry.event && is401(retry.event)) {
    yield reconnectEvent(state.current.provider, '');
    return;
  }
  yield* retry.replay();
}

/** A stream's first event plus a way to re-emit it followed by the rest. */
interface PeekedStream {
  event: HarnessEvent | undefined;
  replay(): AsyncGenerator<HarnessEvent, void, unknown>;
}

/** Pull the first event from a stream without losing it. */
async function firstEvent(stream: AsyncGenerator<HarnessEvent, void, unknown>): Promise<PeekedStream> {
  const head = await stream.next();
  const event = head.done ? undefined : head.value;
  return {
    event,
    async *replay() {
      if (event) yield event;
      yield* stream;
    },
  };
}

/** Strip a trailing `/mcp` from the MCP URL to get the app base URL. */
function appBaseUrlFrom(mcpUrl: string): string {
  return mcpUrl.replace(/\/mcp\/?$/, '');
}

/**
 * Adapter factory that adds 401 refresh when the env can reach the app;
 * otherwise it is plain {@link createProviderAdapter}.
 */
export function createRefreshingAdapterFactory(
  env: NodeJS.ProcessEnv,
  onNewToken?: (token: string) => void,
  fetchFn?: typeof fetch,
): (opts: ProviderAdapterOptions) => ProviderAdapter {
  const agentToken = env.AGENT_API_TOKEN;
  const mcpUrl = env.TRUTHCV_MCP_URL;
  if (!agentToken || !mcpUrl) return createProviderAdapter;
  const refresher = createAppTokenRefresher({
    appBaseUrl: appBaseUrlFrom(mcpUrl),
    agentToken,
    fetchFn,
    onNewToken,
  });
  return (opts) => withAuthRefresh(opts, createProviderAdapter, refresher);
}
