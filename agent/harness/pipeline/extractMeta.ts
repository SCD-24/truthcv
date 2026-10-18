/**
 * The 'extract' stage: pull {role, company, posted_date} from posting text
 * with the extract-stage adapter. The harvest title is the role fallback; an
 * empty company means the posting is unusable (a screening_blocker).
 */
import type { ProviderAdapter } from '../providers/types.js';

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

/** Provider attempts per extraction (mirrors SCREENING_ATTEMPTS). */
const EXTRACT_ATTEMPTS = 2;

/**
 * Outcome: metadata, a blocker when a successful reply named no company, or a
 * provider failure (both attempts errored; not a screening blocker).
 */
export type ExtractResult =
  | { ok: true; meta: PostingMeta }
  | { ok: false; screening_blocker: 'unreadable'; reason: string }
  | { ok: false; failed: true; reason: string };

function field(v: unknown): string {
  return typeof v === 'string' ? v.trim() : '';
}

/** Collect the model's text reply, or the provider error. */
async function complete(adapter: ProviderAdapter, text: string): Promise<{ text: string } | { error: string }> {
  let out = '';
  for await (const ev of adapter.sendMessage({
    systemPrompt: EXTRACT_SYSTEM_PROMPT,
    messages: [{ role: 'user', content: text.slice(0, MAX_EXTRACT_CHARS) }],
    tools: [],
    maxTokens: 512,
  })) {
    if (ev.type === 'text') out += ev.delta;
    if (ev.type === 'done' && !out) out = ev.message.content;
    if (ev.type === 'error') return { error: ev.message || 'provider error' };
  }
  return { text: out };
}

/** One attempt, turning a thrown exception into an error result. */
async function attempt(adapter: ProviderAdapter, text: string): Promise<{ text: string } | { error: string }> {
  try {
    return await complete(adapter, text);
  } catch (err) {
    return { error: err instanceof Error ? err.message : String(err) };
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
 */
export async function extractMeta(adapter: ProviderAdapter, text: string, harvestTitle: string): Promise<ExtractResult> {
  let reply: { text: string } | { error: string } = { error: 'no attempt made' };
  for (let i = 0; i < EXTRACT_ATTEMPTS; i++) {
    reply = await attempt(adapter, text);
    if ('text' in reply) break;
  }
  if ('error' in reply) return { ok: false, failed: true, reason: `extract provider failed: ${reply.error}` };
  const obj = parseObject(reply.text);
  const company = field(obj.company);
  if (!company) return { ok: false, screening_blocker: 'unreadable', reason: 'could not determine the employing company' };
  return { ok: true, meta: { role: field(obj.role) || harvestTitle.trim(), company, posted_date: field(obj.posted_date) } };
}
