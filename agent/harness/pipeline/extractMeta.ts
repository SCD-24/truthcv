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

/** Outcome: metadata, or a blocker when no company could be determined. */
export type ExtractResult = { ok: true; meta: PostingMeta } | { ok: false; screening_blocker: 'unreadable'; reason: string };

function field(v: unknown): string {
  return typeof v === 'string' ? v.trim() : '';
}

/** Collect the model's text reply; empty string on error. */
async function complete(adapter: ProviderAdapter, text: string): Promise<string> {
  let out = '';
  for await (const ev of adapter.sendMessage({
    systemPrompt: EXTRACT_SYSTEM_PROMPT,
    messages: [{ role: 'user', content: text.slice(0, MAX_EXTRACT_CHARS) }],
    tools: [],
    maxTokens: 512,
  })) {
    if (ev.type === 'text') out += ev.delta;
    if (ev.type === 'done' && !out) out = ev.message.content;
    if (ev.type === 'error') return '';
  }
  return out;
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
  let obj: Record<string, unknown> = {};
  try {
    obj = parseObject(await complete(adapter, text));
  } catch {
    obj = {};
  }
  const company = field(obj.company);
  if (!company) return { ok: false, screening_blocker: 'unreadable', reason: 'could not determine the employing company' };
  return { ok: true, meta: { role: field(obj.role) || harvestTitle.trim(), company, posted_date: field(obj.posted_date) } };
}
