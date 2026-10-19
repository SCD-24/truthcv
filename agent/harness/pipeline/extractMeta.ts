/**
 * The 'extract' stage: pull {role, company, posted_date} from posting text
 * with the extract-stage adapter. The harvest title is the role fallback; an
 * empty company means the posting is unusable (a screening_blocker).
 */
import type { ProviderAdapter } from '../providers/types.js';
import {
  PIPELINE_MAX_RETRY_DELAY_MS,
  PROVIDER_RETRY_ATTEMPTS,
  realSleep,
  retryDelayMs,
  type Sleep,
} from '../providers/retry.js';

/** Max posting characters sent to the extractor. */
export const MAX_EXTRACT_CHARS = 12000;

const EXTRACT_SYSTEM_PROMPT =
  'Extract metadata from a job posting. Reply with ONLY a JSON object ' +
  '{"role": string, "company": string, "posted_date": string}. ' +
  'role is the posting\'s job title; company is the employing entity; ' +
  'posted_date is the publication date only if the text states one, else "". ' +
  'Use "" for anything not stated. Never guess.';

/** Extracted posting metadata. */
export interface PostingMeta {
  role: string;
  company: string;
  posted_date: string;
}

/** Cap on the extractor's reply; roomy enough that a reasoning model still finishes the JSON. */
const EXTRACT_MAX_TOKENS = 1024;

/** Immediate attempts for a non-retryable failure or cut-off reply (mirrors SCREENING_ATTEMPTS). */
const EXTRACT_ATTEMPTS = 2;

/** Options for {@link extractMeta}. */
export interface ExtractMetaOptions {
  /** Injectable sleep between retryable provider attempts. */
  sleep?: Sleep;
}

/**
 * Outcome: metadata, a blocker when a successful reply named no company, or a
 * failure (not a screening blocker). `provider` is true when the failure was a
 * provider error or throw, false for a reply cut off at the token limit.
 */
export type ExtractResult =
  | { ok: true; meta: PostingMeta }
  | { ok: false; screening_blocker: 'unreadable'; reason: string }
  | { ok: false; failed: true; provider: boolean; reason: string };

/** A failed attempt: the raw message and how it may be retried. */
interface AttemptFailure {
  error: string;
  provider: boolean;
  retryable: boolean;
  retryAfterMs?: number;
}

/** One attempt's result. */
type AttemptResult = { text: string } | AttemptFailure;

function field(v: unknown): string {
  return typeof v === 'string' ? v.trim() : '';
}

/** Collect the model's text reply, or the provider error. */
async function complete(adapter: ProviderAdapter, text: string): Promise<AttemptResult> {
  let out = '';
  let truncated = false;
  for await (const ev of adapter.sendMessage({
    systemPrompt: EXTRACT_SYSTEM_PROMPT,
    messages: [{ role: 'user', content: text.slice(0, MAX_EXTRACT_CHARS) }],
    tools: [],
    maxTokens: EXTRACT_MAX_TOKENS,
  })) {
    if (ev.type === 'text') out += ev.delta;
    if (ev.type === 'done' && !out) out = ev.message.content;
    if (ev.type === 'done' && ev.stopReason === 'length') truncated = true;
    if (ev.type === 'error') {
      return { error: ev.message || 'provider error', provider: true, retryable: ev.retryable, retryAfterMs: ev.retryAfterMs };
    }
  }
  if (truncated) return { error: `extract reply was cut off at the ${EXTRACT_MAX_TOKENS}-token limit`, provider: false, retryable: false };
  return { text: out };
}

/** One attempt, turning a thrown exception into an error result. */
async function attempt(adapter: ProviderAdapter, text: string): Promise<AttemptResult> {
  try {
    return await complete(adapter, text);
  } catch (err) {
    return { error: err instanceof Error ? err.message : String(err), provider: true, retryable: true };
  }
}

/**
 * Call the extractor until it replies or the retry budget is spent: retryable
 * failures get PROVIDER_RETRY_ATTEMPTS tries with backoff, others get
 * EXTRACT_ATTEMPTS immediate tries.
 */
async function replyWithRetry(adapter: ProviderAdapter, text: string, sleep: Sleep): Promise<AttemptResult> {
  let immediate = 0;
  let delayed = 0;
  for (;;) {
    const reply = await attempt(adapter, text);
    if ('text' in reply) return reply;
    if (!reply.retryable) {
      immediate += 1;
      if (immediate >= EXTRACT_ATTEMPTS) return reply;
      continue;
    }
    delayed += 1;
    if (delayed >= PROVIDER_RETRY_ATTEMPTS) return reply;
    await sleep(retryDelayMs(delayed - 1, reply.retryAfterMs, PIPELINE_MAX_RETRY_DELAY_MS));
  }
}

/** Parse the first JSON object in `raw`. */
function parseObject(raw: string): Record<string, unknown> {
  const m = /\{[\s\S]*\}/.exec(raw);
  if (!m) return {};
  try {
    return JSON.parse(m[0]) as Record<string, unknown>;
  } catch {
    return {};
  }
}

/**
 * Extract posting metadata.
 *
 * @param adapter The extract-stage adapter.
 * @param text Full readable posting text.
 * @param harvestTitle The discovery title, used when the model finds no role.
 * @param opts Optional injectable sleep for retry backoff.
 */
export async function extractMeta(adapter: ProviderAdapter, text: string, harvestTitle: string, opts: ExtractMetaOptions = {}): Promise<ExtractResult> {
  const reply = await replyWithRetry(adapter, text, opts.sleep ?? realSleep);
  if ('error' in reply) {
    const reason = reply.provider ? `extract provider failed: ${reply.error}` : reply.error;
    return { ok: false, failed: true, provider: reply.provider, reason };
  }
  const obj = parseObject(reply.text);
  const company = field(obj.company);
  if (!company) return { ok: false, screening_blocker: 'unreadable', reason: 'could not determine the employing company' };
  return { ok: true, meta: { role: field(obj.role) || harvestTitle.trim(), company, posted_date: field(obj.posted_date) } };
}
