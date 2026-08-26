import { createHash } from 'node:crypto';

/** The maximum length permitted for a namespaced tool name. */
const MAX_LENGTH = 64;

/**
 * A (server, tool) pair to be namespaced.
 */
export interface ToolRef {
  /** The MCP server key the tool belongs to. */
  serverName: string;
  /** The tool's own name as reported by that server. */
  toolName: string;
}

/**
 * Build a stable, sanitised, length-bounded namespaced name for one tool.
 *
 * The name is `${serverName}__${toolName}`, with every character outside
 * `[A-Za-z0-9_-]` replaced by `_`. If the sanitised result exceeds 64
 * characters it is truncated and a `-` plus an 8-hex-char SHA-1 hash of the
 * FULL (untruncated) sanitised name is appended, keeping the final string
 * `<= 64` characters while distinguishing names that share a truncated prefix.
 *
 * @param serverName The owning MCP server key.
 * @param toolName The tool's own name.
 * @returns A sanitised namespaced name of at most 64 characters.
 */
export function namespaceTool(serverName: string, toolName: string): string {
  const full = sanitize(`${serverName}__${toolName}`);
  if (full.length <= MAX_LENGTH) return full;
  const hash = createHash('sha1').update(full).digest('hex').slice(0, 8);
  return `${full.slice(0, MAX_LENGTH - 9)}-${hash}`;
}

/**
 * Namespace a whole tool set, resolving cross-server name collisions.
 *
 * Runs {@link namespaceTool} over every pair and, whenever a later pair
 * produces a name already taken by an earlier one, appends a numeric
 * disambiguator (`-1`, `-2`, ...), truncating as needed so the result stays
 * `<= 64` characters and remains unique.
 *
 * @param pairs The (serverName, toolName) pairs to namespace.
 * @returns A map from each final unique namespaced name to its source pair.
 */
export function namespaceTools(pairs: ToolRef[]): Map<string, ToolRef> {
  const result = new Map<string, ToolRef>();
  for (const pair of pairs) {
    const unique = disambiguate(namespaceTool(pair.serverName, pair.toolName), result);
    result.set(unique, { serverName: pair.serverName, toolName: pair.toolName });
  }
  return result;
}

/** Replace every character outside `[A-Za-z0-9_-]` with `_`. */
function sanitize(name: string): string {
  return name.replace(/[^A-Za-z0-9_-]/g, '_');
}

/** Return `base` if free, else `base` with the smallest unused numeric suffix. */
function disambiguate(base: string, taken: Map<string, ToolRef>): string {
  if (!taken.has(base)) return base;
  let n = 1;
  let candidate = withSuffix(base, n);
  while (taken.has(candidate)) {
    n += 1;
    candidate = withSuffix(base, n);
  }
  return candidate;
}

/** Append `-<n>` to `base`, truncating the base so the result stays <= 64 chars. */
function withSuffix(base: string, n: number): string {
  const suffix = `-${n}`;
  return `${base.slice(0, MAX_LENGTH - suffix.length)}${suffix}`;
}
