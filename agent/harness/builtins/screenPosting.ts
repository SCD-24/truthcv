/**
 * The harness's `screen_posting` built-in tool: screens ONE discovered
 * posting against a job profile's criteria in an ISOLATED conversation,
 * driven by its own (typically cheaper) provider adapter — never the main
 * loop's model or its growing context.
 *
 * The point is cost, not capability: the main loop's model still has to hold
 * a posting's text to hand it to this tool, but the VERBOSE part of
 * screening — working through every hard filter, weighing the posting's
 * stated remote arrangement and language requirement against the matched
 * profile — happens here, in a brand-new `ConversationMessage[]` with no
 * tool definitions and no prior turns, sent to a model that can be
 * configured far cheaper than the one driving the whole run. Only the
 * compact structured verdict below travels back into the main loop's
 * context; the reasoning that produced it never does.
 *
 * This tool does NOT replace `record_screening`. It has no access to the
 * screening ledger and writes nothing: `screening/store.py`'s `create()`
 * (via `create_or_get`) is the only path that persists a screening record,
 * and the agent must still call the MCP `record_screening` tool for every
 * posting, verdict included, exactly as `agent/RUNBOOK.md` requires. This
 * verdict is only ever an INPUT to that call, shaped to match what it
 * validates (see the field comments below, and `screening/model.py` /
 * `screening/criteria.py`, whose value sets are mirrored here so a verdict
 * this tool returns is never rejected downstream for an unrecognised value).
 */

import type {
  ConversationMessage,
  ModelRequest,
  ProviderAdapter,
  ToolDefinition,
} from '../providers/types.js';

/** Raw arguments as the model supplies them via the tool call. */
export interface ScreenPostingArgs {
  /** The posting's own URL, exactly as opened. */
  url: string;
  /** The posting's job title, exactly as posted. */
  role: string;
  /** The employing entity's name. */
  company: string;
  /** The posting's full text, as read from the page. */
  postingText: string;
  /** The enabled JobProfile name being screened against. */
  profile: string;
  /** The matched profile's full criteria, rendered as free text (remote
   * model, working language, salary band, employment country, accepted and
   * rejected role types, and any other hard filter from RUNBOOK §2). */
  criteria: string;
}

/**
 * The verdict the isolated screening model returns, parsed into this
 * internal (camelCase) shape. Every field maps onto a `record_screening`
 * argument of the same purpose, but under camelCase names that are internal
 * to this file: the JSON {@link screenPosting} actually hands back to the
 * calling model is renamed onto `record_screening`'s own snake_case argument
 * names first (see {@link toRecordScreeningFields}), so the caller can pass
 * it straight through without reshaping a single key.
 */
export interface ScreeningVerdict {
  /** One of `VERDICT_VALUES`, or '' when `screeningBlocker` is set instead. */
  verdict: string;
  /** Non-empty only when the posting could not be read at all — one of
   * `BLOCKER_VALUES`. Mutually exclusive with a non-empty `verdict`. */
  screeningBlocker: string;
  /** Which criterion failed, when rejected; '' otherwise. Free text, e.g.
   * `screening/criteria.py`'s `"remote_model"` / `"working_language"`, or a
   * hard-filter name of this tool's own choosing. */
  failingCriterion: string;
  /** One-line human-readable explanation of the verdict. */
  reason: string;
  /** The posting's OWN stated remote arrangement — one of
   * `REMOTE_ARRANGEMENT_VALUES` — never the profile's. */
  remoteArrangement: string;
  /** A working language the posting explicitly requires, free text, or ''
   * when it states none. */
  languageRequirement: string;
}

/** The result shape this handler returns, mirroring every other built-in's
 * `{ content, isError }` (see `readRunbook.ts`). */
export interface ScreenPostingResult {
  /** The JSON-encoded verdict, keyed with `record_screening`'s own snake_case
   * argument names (see {@link toRecordScreeningFields}), or an error message. */
  content: string;
  /** True when the posting could not be screened at all. */
  isError: boolean;
}

/**
 * `verdict` values `screening/model.py`'s `VERDICT_VALUES` recognises, plus
 * '' for "no verdict, a blocker instead". Duplicated here — this is a
 * separate TypeScript/Python boundary, not an import — so a value produced
 * here is never rejected by `screening.store.create` downstream.
 */
const VERDICT_VALUES = ['passed', 'rejected', 'deferred', ''] as const;

/** Mirrors `screening/model.py`'s `BLOCKER_VALUES`. */
const BLOCKER_VALUES = ['', 'login_required', 'unreadable', 'not_found', 'expired'] as const;

/** Mirrors `screening/criteria.py`'s `REMOTE_ARRANGEMENT_VALUES`. */
const REMOTE_ARRANGEMENT_VALUES = ['', 'remote', 'hybrid', 'on_site', 'unstated'] as const;

/** The provider-facing definition advertised to the main loop's model. */
export const screenPostingTool: ToolDefinition = {
  name: 'screen_posting',
  description:
    "Screen ONE discovered posting against a job profile's criteria in an isolated " +
    'subagent context, backed by a separate (often cheaper) model — instead of reasoning ' +
    "through every hard filter yourself, in this conversation. Returns a compact verdict, " +
    "using record_screening's own argument names so it can be passed straight through: " +
    "'verdict' (passed/rejected/deferred, or '' with a screening_blocker), 'failing_criterion', " +
    "'reason', 'remote_arrangement' and 'language_requirement' (the posting's OWN stated " +
    "values, not the profile's). This tool NEVER records anything — you must still call " +
    'record_screening yourself with this verdict and the posting_text you already hold; ' +
    'the approve/deny gate is unaffected by this tool and enforced only there.',
  inputSchema: {
    type: 'object',
    properties: {
      url: { type: 'string', description: "The posting's own URL, exactly as opened." },
      role: { type: 'string', description: "The posting's job title, exactly as posted." },
      company: { type: 'string', description: "The employing entity's name." },
      postingText: { type: 'string', description: "The posting's full text, as read from the page." },
      profile: { type: 'string', description: 'The enabled JobProfile name being screened against.' },
      criteria: {
        type: 'string',
        description:
          "The matched profile's full criteria as free text (remote model, working " +
          'language, salary band, employment country, accepted/rejected role types, and ' +
          'any other RUNBOOK §2 hard filter).',
      },
    },
    required: ['url', 'role', 'company', 'postingText', 'profile', 'criteria'],
    additionalProperties: false,
  },
};

/** Cap on the screening subagent's reply — a compact verdict, never prose. */
const SCREENING_MAX_TOKENS = 700;

/** The system prompt for the isolated screening conversation. Carries no
 * tool definitions and no history: this call answers ONE question, once. */
const SCREENING_SYSTEM_PROMPT =
  'You screen a single job posting against one profile\'s hard filters. Read the posting ' +
  'text and the criteria below, then reply with EXACTLY ONE JSON object and nothing else — ' +
  'no prose, no markdown fences — with these keys: "verdict" (one of "passed", "rejected", ' +
  '"deferred", or "" if the posting could not be evaluated), "screeningBlocker" (one of "", ' +
  '"login_required", "unreadable", "not_found", "expired" — non-empty only when verdict is ' +
  'empty), "failingCriterion" (which criterion failed, or ""), "reason" (one line explaining ' +
  'the verdict), "remoteArrangement" (the POSTING\'S OWN stated remote arrangement: "remote", ' +
  '"hybrid", "on_site", "unstated" if it does not say, or "" if not applicable), and ' +
  '"languageRequirement" (a language the posting explicitly requires, or ""). Never guess a ' +
  'verdict for a posting you could not read — use screeningBlocker instead. Judge only the ' +
  'stated criteria; never invent facts the posting does not state.';

/** Build the isolated conversation's one user turn from the tool arguments. */
function buildScreeningPrompt(args: ScreenPostingArgs): string {
  return (
    `Profile: ${args.profile}\n\n` +
    `Criteria:\n${args.criteria}\n\n` +
    `Posting company: ${args.company}\n` +
    `Posting role: ${args.role}\n` +
    `Posting URL: ${args.url}\n\n` +
    `Posting text:\n${args.postingText}`
  );
}

/** Required string fields; screen_posting refuses the call without them. */
const REQUIRED_FIELDS: (keyof ScreenPostingArgs)[] = [
  'url',
  'role',
  'company',
  'postingText',
  'profile',
  'criteria',
];

/** Read a string field out of the raw tool arguments, defaulting to ''. */
function stringField(args: Record<string, unknown>, key: string): string {
  const value = args[key];
  return typeof value === 'string' ? value : '';
}

/** Coerce raw tool-call arguments into {@link ScreenPostingArgs}, never throwing. */
function coerceArgs(raw: Record<string, unknown>): ScreenPostingArgs {
  return {
    url: stringField(raw, 'url'),
    role: stringField(raw, 'role'),
    company: stringField(raw, 'company'),
    postingText: stringField(raw, 'postingText'),
    profile: stringField(raw, 'profile'),
    criteria: stringField(raw, 'criteria'),
  };
}

/** Names of required fields left blank after coercion, in schema order. */
function missingFields(args: ScreenPostingArgs): string[] {
  return REQUIRED_FIELDS.filter((key) => !args[key].trim());
}

/**
 * Drain the adapter's event stream for one screening call.
 *
 * Assumes only what {@link ProviderAdapter}'s contract already promises: a
 * provider failure arrives as an `error` HarnessEvent, not a rejection. Any
 * unexpected throw out of `sendMessage` is the caller's problem to catch,
 * which {@link screenPosting} does.
 *
 * @param adapter The (separate, cheaper) screening provider adapter.
 * @param request The one-shot screening request.
 * @returns The assembled reply text, or the provider's error message.
 */
async function collectScreeningReply(
  adapter: ProviderAdapter,
  request: ModelRequest,
): Promise<{ text: string; error?: string }> {
  for await (const event of adapter.sendMessage(request)) {
    if (event.type === 'error') return { text: '', error: event.message };
    if (event.type === 'done') return { text: event.message.content };
  }
  return { text: '' };
}

/** Whether `value` is one of the given known values. */
function isKnownValue(value: unknown, known: readonly string[]): value is string {
  return typeof value === 'string' && known.includes(value);
}

/**
 * Parse and validate the screening subagent's JSON reply into a
 * {@link ScreeningVerdict}, or undefined when it is not a well-formed one.
 *
 * Every enumerated field is checked against its known value set (mirroring
 * `screening/model.py` and `screening/criteria.py`) so a malformed reply is
 * caught HERE rather than surfacing later as a rejected `record_screening`
 * call the caller cannot explain. `verdict` and `screeningBlocker` are
 * mutually exclusive, exactly as `screening/model.py`'s `validate_verdict`
 * requires — a reply with neither is invalid.
 */
function parseVerdict(text: string): ScreeningVerdict | undefined {
  let parsed: unknown;
  try {
    parsed = JSON.parse(text);
  } catch {
    return undefined;
  }
  if (typeof parsed !== 'object' || parsed === null) return undefined;
  const raw = parsed as Record<string, unknown>;
  if (!isKnownValue(raw.verdict, VERDICT_VALUES)) return undefined;
  if (!isKnownValue(raw.screeningBlocker, BLOCKER_VALUES)) return undefined;
  if (!isKnownValue(raw.remoteArrangement, REMOTE_ARRANGEMENT_VALUES)) return undefined;
  if (!raw.verdict && !raw.screeningBlocker) return undefined;
  return {
    verdict: raw.verdict,
    screeningBlocker: raw.screeningBlocker,
    failingCriterion: typeof raw.failingCriterion === 'string' ? raw.failingCriterion : '',
    reason: typeof raw.reason === 'string' ? raw.reason : '',
    remoteArrangement: raw.remoteArrangement,
    languageRequirement: typeof raw.languageRequirement === 'string' ? raw.languageRequirement : '',
  };
}

/** Coerce an unknown thrown value into a message string. */
function errorMessage(err: unknown): string {
  return err instanceof Error ? err.message : String(err);
}

/** Run the isolated screening request, returning a verdict or an error message. */
async function runScreening(
  adapter: ProviderAdapter,
  request: ModelRequest,
): Promise<{ verdict?: ScreeningVerdict; errorContent?: string }> {
  let reply: { text: string; error?: string };
  try {
    reply = await collectScreeningReply(adapter, request);
  } catch (err) {
    return { errorContent: `screen_posting provider call failed: ${errorMessage(err)}` };
  }
  if (reply.error) return { errorContent: `screen_posting provider error: ${reply.error}` };
  const verdict = parseVerdict(reply.text);
  if (!verdict) return { errorContent: 'screen_posting: the screening model did not return a valid verdict' };
  return { verdict };
}

/**
 * Rename a {@link ScreeningVerdict}'s fields onto `record_screening`'s own
 * snake_case argument names, so the calling model can pass this tool's JSON
 * straight through to `record_screening` without reshaping a single key.
 * Values are copied verbatim — only the field NAMES change; `verdict` and
 * `reason` already match record_screening's own names and pass through
 * unchanged.
 *
 * @param verdict The internal, camelCase verdict to rename.
 * @returns The same values, keyed with record_screening's own argument names.
 */
function toRecordScreeningFields(verdict: ScreeningVerdict): Record<string, string> {
  return {
    verdict: verdict.verdict,
    screening_blocker: verdict.screeningBlocker,
    failing_criterion: verdict.failingCriterion,
    reason: verdict.reason,
    remote_arrangement: verdict.remoteArrangement,
    language_requirement: verdict.languageRequirement,
  };
}

/**
 * Screen one posting in an isolated conversation, against a separate
 * (typically cheaper) provider adapter.
 *
 * Never throws: a missing required argument, a provider error, or a reply
 * that fails to parse as a valid verdict is returned as an `isError` result
 * the calling model can read and recover from (e.g. by retrying, or by
 * recording a `screening_blocker` of its own via `record_screening`).
 *
 * @param rawArgs The raw tool-call arguments.
 * @param adapter The screening provider adapter, built separately from and
 *   never shared with the main loop's own adapter.
 * @returns The structured verdict, or an error message, with `isError` set.
 */
export async function screenPosting(
  rawArgs: Record<string, unknown>,
  adapter: ProviderAdapter,
): Promise<ScreenPostingResult> {
  const args = coerceArgs(rawArgs);
  const missing = missingFields(args);
  if (missing.length > 0) {
    return { content: `screen_posting requires: ${missing.join(', ')}`, isError: true };
  }
  const request: ModelRequest = {
    systemPrompt: SCREENING_SYSTEM_PROMPT,
    messages: [{ role: 'user', content: buildScreeningPrompt(args) } as ConversationMessage],
    tools: [],
    maxTokens: SCREENING_MAX_TOKENS,
  };
  const { verdict, errorContent } = await runScreening(adapter, request);
  if (errorContent || !verdict) {
    return { content: errorContent ?? 'screen_posting: the screening model did not return a valid verdict', isError: true };
  }
  return { content: JSON.stringify(toRecordScreeningFields(verdict)), isError: false };
}
