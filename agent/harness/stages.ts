/**
 * Stage registry and per-stage model routing.
 *
 * Each pipeline stage (apply, screening, extract) may run on its own model.
 * The backend prints a routes document (`agent-config.js llm_routes`) which
 * daily-apply.sh writes to a 0600 temp file and hands to the CLI through
 * `--routes-file`. Adding a stage is one entry in {@link STAGE_REGISTRY}.
 */

import type { Provider, Wire } from './providers/registry.js';

/** Credentials + model for one stage (same shape as `llm_credentials`). */
export interface StageRoute {
  authType?: 'oauth' | 'api_key' | 'url';
  token: string;
  model: string;
  baseUrl: string;
  provider: Provider;
  wire: Wire;
}

/** One registry entry: the stage name and the stage it falls back to when unrouted. */
export interface StageDefinition {
  name: string;
  /** Stage whose resolved route is used when this stage has none; null = the main model. */
  fallback: string | null;
  /** RUNBOOK.md section headings composed into this stage's static system prompt. */
  runbookSections?: readonly string[];
  /** prompt.md section headings composed into this stage's static system prompt. */
  promptSections?: readonly string[];
}

/** Names of the registered stages. */
export type StageName = 'apply' | 'screening' | 'extract';

/** Registry, ordered so every fallback precedes its dependants. Extend by adding one entry. */
export const STAGE_REGISTRY = [
  {
    name: 'apply',
    fallback: null,
    runbookSections: [
      '3. Canonical answers — call `get_profile_answers`',
      '4. Truthfulness rules — non-negotiable',
      'Applying to a passed posting',
      'Both documents go up — the CV **and** the letter, but never at the CV\'s cost',
      '6. The approve/deny boundary',
    ],
    promptSections: ['Your tools', 'Run identity', 'The approve/deny boundary', 'Autonomy mode'],
  },
  { name: 'screening', fallback: 'apply' },
  { name: 'extract', fallback: 'screening' },
] as const satisfies readonly StageDefinition[];

/** The registry keyed by stage name. */
export const STAGES: Record<StageName, StageDefinition> = Object.fromEntries(
  STAGE_REGISTRY.map((d) => [d.name, d]),
) as Record<StageName, StageDefinition>;


/** Routes as delivered by the backend: a stage is absent or null when unrouted. */
export type RoutesDocument = Partial<Record<StageName, StageRoute | null>>;

/** Fully resolved routes: every stage has a concrete route. */
export type ResolvedRoutes = Record<StageName, StageRoute>;

/** Per-stage explicit overrides (flags/env); only defined fields win. */
export type RouteOverrides = Partial<Record<StageName, Partial<StageRoute>>>;

/** True when `value` looks like a usable route (a model and a provider). */
function isRoute(value: unknown): value is StageRoute {
  const v = value as Partial<StageRoute> | null;
  return Boolean(v && typeof v === 'object' && v.model && v.provider && v.wire);
}

/**
 * Parse the `llm_routes` JSON (`{"stages": {...}}`, or the bare stages map).
 * Malformed input yields an empty document rather than throwing.
 */
export function parseRoutes(text: string): RoutesDocument {
  let raw: unknown;
  try {
    raw = JSON.parse(text);
  } catch {
    return {};
  }
  const stages = ((raw as { stages?: unknown })?.stages ?? raw) as Record<string, unknown> | null;
  const doc: RoutesDocument = {};
  for (const { name } of STAGE_REGISTRY) {
    const candidate = stages?.[name];
    doc[name] = isRoute(candidate) ? { ...candidate, token: candidate.token ?? '', baseUrl: candidate.baseUrl ?? '' } : null;
  }
  return doc;
}

/** Drop undefined fields so a spread override never erases a value. */
function definedFields(partial: Partial<StageRoute> | undefined): Partial<StageRoute> {
  const out: Record<string, unknown> = {};
  for (const [k, v] of Object.entries(partial ?? {})) if (v !== undefined) out[k] = v;
  return out as Partial<StageRoute>;
}

/**
 * Resolve every stage: explicit override fields > the stage's own route >
 * its fallback stage's resolved route > the main model. Registry order
 * guarantees a fallback is resolved before use.
 */
export function resolveStageRoutes(
  routes: RoutesDocument,
  main: StageRoute,
  overrides: RouteOverrides = {},
): ResolvedRoutes {
  const resolved: Partial<ResolvedRoutes> = {};
  for (const def of STAGE_REGISTRY as readonly StageDefinition[]) {
    const name = def.name as StageName;
    const inherited = def.fallback ? resolved[def.fallback as StageName] : undefined;
    const base = routes[name] ?? inherited ?? main;
    resolved[name] = { ...base, ...definedFields(overrides[name]) };
  }
  return resolved as ResolvedRoutes;
}

/**
 * Resolve a single stage's route (override > own route > fallback chain > main).
 * `main` is the apply stage's base when the routes document has no apply route.
 */
export function resolveStageRoute(
  stage: StageName,
  routes: RoutesDocument,
  overrides: RouteOverrides = {},
  main: StageRoute = { token: '', model: '', baseUrl: '', provider: 'claude', wire: 'anthropic-messages' },
): StageRoute {
  return resolveStageRoutes(routes, main, overrides)[stage];
}
