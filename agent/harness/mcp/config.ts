import { readFileSync } from 'node:fs';

/**
 * A single resolved MCP server: its config key and its fully-expanded URL.
 */
export interface McpServerConfig {
  /** The server key from `mcpServers`, e.g. "truthcv" or "browser". */
  name: string;
  /** The connect URL, with every `${VAR:-default}` placeholder expanded. */
  url: string;
}

/**
 * Expand every `${VAR:-default}` occurrence in `raw` using `env`.
 *
 * For each placeholder the value of `env.VAR` is used when it is set and
 * non-empty; otherwise the literal `default` is substituted. Multiple
 * placeholders in a single string are all expanded. This deliberately does the
 * expansion in-process rather than relying on any external tool (Claude Code
 * used to perform it and no longer will).
 *
 * @param raw The string possibly containing `${VAR:-default}` placeholders.
 * @param env The environment to resolve variables from (typically process.env).
 * @returns The string with all placeholders resolved.
 */
export function expandPlaceholders(raw: string, env: NodeJS.ProcessEnv): string {
  return raw.replace(/\$\{([A-Za-z_][A-Za-z0-9_]*):-([^}]*)\}/g, (_match, name: string, def: string) => {
    const value = env[name];
    return value !== undefined && value !== '' ? value : def;
  });
}

/**
 * Load and normalise an MCP config JSON file into a flat server list.
 *
 * Reads the JSON at `path`, iterates `mcpServers`, skips any key starting with
 * `_` (comment keys), expands `${VAR:-default}` placeholders in each server's
 * `url` via {@link expandPlaceholders}, and returns one {@link McpServerConfig}
 * per server. Only `type: "http"` servers are supported; any other declared
 * type throws a clear error.
 *
 * @param path Filesystem path to the MCP config JSON file.
 * @param env The environment used to expand URL placeholders.
 * @returns One entry per configured HTTP server.
 */
export function loadMcpConfig(path: string, env: NodeJS.ProcessEnv): McpServerConfig[] {
  const parsed = JSON.parse(readFileSync(path, 'utf8')) as { mcpServers?: Record<string, unknown> };
  const servers = parsed.mcpServers ?? {};
  const result: McpServerConfig[] = [];
  for (const [name, cfg] of Object.entries(servers)) {
    if (name.startsWith('_')) continue;
    result.push(parseServer(name, cfg, env));
  }
  return result;
}

/**
 * Validate and normalise one raw server config entry into an McpServerConfig.
 */
function parseServer(name: string, cfg: unknown, env: NodeJS.ProcessEnv): McpServerConfig {
  const server = (cfg ?? {}) as { type?: string; url?: string };
  if (server.type !== 'http') {
    throw new Error(`MCP server '${name}' has unsupported type '${String(server.type)}'; only 'http' is supported`);
  }
  if (typeof server.url !== 'string') {
    throw new Error(`MCP server '${name}' is missing a string 'url'`);
  }
  return { name, url: expandPlaceholders(server.url, env) };
}
