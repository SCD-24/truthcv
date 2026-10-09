/**
 * Persisted Google dork-search state, shared across runs so pacing and the
 * block cooldown survive process restarts: when the last search happened, the
 * consecutive-block count, the cooldown end, and which queries were deferred.
 */
import { readFile, rename, writeFile } from 'node:fs/promises';

/** Cross-run dork search state (all times are epoch ms). */
export interface DorkState {
  /** When the last Google search started; 0 when none is known. */
  lastSearchAt: number;
  /** Consecutive Google-blocked searches so far. */
  consecutiveBlocks: number;
  /** No search is allowed before this time; 0 when not cooling down. */
  cooldownUntil: number;
  /** Coverage board names of queries deferred (not searched), to be searched first next run. */
  deferred: string[];
}

/** Injectable file access. */
export interface DorkStateFs {
  readFileText: (path: string) => Promise<string>;
  writeFileText: (path: string, text: string) => Promise<void>;
  /** Atomically moves `from` over `to`. */
  renameFile: (from: string, to: string) => Promise<void>;
}

const realFs: DorkStateFs = {
  readFileText: (p) => readFile(p, 'utf8'),
  writeFileText: (p, t) => writeFile(p, t, 'utf8'),
  renameFile: (a, b) => rename(a, b),
};

/** A fresh state: nothing searched, no cooldown, nothing deferred. */
export function defaultDorkState(): DorkState {
  return { lastSearchAt: 0, consecutiveBlocks: 0, cooldownUntil: 0, deferred: [] };
}

function num(v: unknown): number {
  return typeof v === 'number' && Number.isFinite(v) && v >= 0 ? v : 0;
}

/** An epoch-ms time that converts to a valid Date (else 0, i.e. absent). */
function epoch(v: unknown): number {
  const n = num(v);
  return Number.isNaN(new Date(n).getTime()) ? 0 : n;
}

/**
 * Load the state from `path`; a missing, unreadable or corrupt file yields the defaults (never throws).
 *
 * @param path State file path.
 * @param fs Injectable file access.
 */
export async function loadDorkState(path: string, fs: DorkStateFs = realFs): Promise<DorkState> {
  try {
    const raw = JSON.parse(await fs.readFileText(path)) as Record<string, unknown> | null;
    if (!raw || typeof raw !== 'object') return defaultDorkState();
    const deferred = Array.isArray(raw.deferred) ? raw.deferred.filter((x): x is string => typeof x === 'string') : [];
    return { lastSearchAt: epoch(raw.lastSearchAt), consecutiveBlocks: Math.floor(num(raw.consecutiveBlocks)), cooldownUntil: epoch(raw.cooldownUntil), deferred };
  } catch {
    return defaultDorkState();
  }
}

/**
 * Persist the state to `path` atomically (temp file then rename); returns an error string on failure (never throws).
 *
 * @param path State file path.
 * @param state State to write.
 * @param fs Injectable file access.
 */
export async function saveDorkState(path: string, state: DorkState, fs: DorkStateFs = realFs): Promise<string | undefined> {
  try {
    const tmp = `${path}.tmp`;
    await fs.writeFileText(tmp, JSON.stringify(state));
    await fs.renameFile(tmp, path);
    return undefined;
  } catch (err) {
    return `dork state not saved: ${err instanceof Error ? err.message : String(err)}`;
  }
}
