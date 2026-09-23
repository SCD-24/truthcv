/**
 * Screen one full posting with the existing isolated evaluator and persist its
 * verdict through the live, allow-listed record_screening MCP tool. The
 * persisted record, not the proposed model verdict, governs what happens next.
 */
import type { ProviderAdapter, ToolDefinition } from '../providers/types.js';
import { screenPosting } from './screenPosting.js';

/** Only these metadata fields may be supplied by the caller; evidence is model-produced. */
const INPUT_FIELDS = ['url', 'role', 'company', 'postingText', 'profile', 'criteria', 'run_id', 'source', 'posted_date'] as const;
const REQUIRED_FIELDS = INPUT_FIELDS.slice(0, 7);
const EVIDENCE_FIELDS = [
  'verdict', 'screening_blocker', 'failing_criterion', 'reason', 'remote_arrangement',
  'language_requirement', 'salary_stated', 'employment_country_stated', 'role_type_stated', 'eor_stated',
] as const;

export const screenAndRecordPostingTool: ToolDefinition = {
  name: 'screen_and_record_posting',
  description:
    'Screen ONE posting from its full text against a matched profile, then persist the verdict via record_screening before returning. ' +
    'Pass the real posting url, role, company, postingText, profile, full criteria and run_id; source and posted_date are optional. ' +
    'Do not pass a verdict or evidence yourself. Returns a compact STORED outcome (id, verdict, screening_blocker, created, actionable), not the posting text. ' +
    'actionable is true only for a newly recorded stored pass without a blocker. A server downgrade to rejected is final; ' +
    'created:false means skip, not retry. Do not call record_screening again on success. On a screening or recording error ' +
    'there is no actionable verdict: stop acting on this posting, not the entire run. Continue other work and coverage; ' +
    'ask the operator to check its URL in the JSON from GET /api/screenings before any manual recovery.',
  inputSchema: {
    type: 'object',
    properties: {
      url: { type: 'string', description: "The posting's own URL." },
      role: { type: 'string', description: "The posting's actual job title." },
      company: { type: 'string', description: 'The employing entity.' },
      postingText: { type: 'string', description: 'The full readable posting text.' },
      profile: { type: 'string', description: 'The enabled JobProfile name.' },
      criteria: { type: 'string', description: 'The matched profile\'s complete criteria.' },
      run_id: { type: 'string', description: 'The current run id for attribution.' },
      source: { type: 'string', description: 'Optional discovery source.' },
      posted_date: { type: 'string', description: 'Optional posting publication date, only when stated.' },
    },
    required: REQUIRED_FIELDS,
    additionalProperties: false,
  },
};

export interface ScreenAndRecordResult { content: string; isError: boolean }
export type RecordScreeningCall = (args: Record<string, unknown>) => Promise<{ content: string; isError?: boolean }>;

function validateArgs(args: Record<string, unknown>): string | undefined {
  const unexpected = Object.keys(args).filter((key) => !(INPUT_FIELDS as readonly string[]).includes(key));
  if (unexpected.length) return `screen_and_record_posting does not accept caller verdict/evidence or unknown fields: ${unexpected.join(', ')}`;
  const missing = REQUIRED_FIELDS.filter((key) => typeof args[key] !== 'string' || !(args[key] as string).trim());
  if (missing.length) return `screen_and_record_posting requires: ${missing.join(', ')}`;
  for (const key of ['source', 'posted_date']) {
    if (args[key] !== undefined && typeof args[key] !== 'string') return `screen_and_record_posting requires ${key} to be a string`;
  }
  try {
    if (!['https:', 'http:'].includes(new URL(args.url as string).protocol)) throw new Error('invalid protocol');
  } catch {
    return 'screen_and_record_posting requires an http(s) posting url';
  }
  return undefined;
}

/** Fail closed on an unrecognised response; never return a proposed pass as persisted. */
const RECOVERY = 'Stop acting on this posting, not the entire run; continue other work and coverage. ' +
  'Ask the operator to open GET /api/screenings on the TruthCV app origin (navigate to /api/screenings in their browser) ' +
  'and inspect the returned JSON array\'s url fields for this posting URL to confirm whether a record exists. ' +
  'The /screenings UI does not display URLs; there is no agent screening lookup tool. ' +
  'Do not retry or rescreen automatically; use record_screening manually only after the operator confirms no record exists.';

function storedResult(content: string): ScreenAndRecordResult {
  let raw: unknown;
  try { raw = JSON.parse(content); } catch { /* malformed server response */ }
  if (!raw || typeof raw !== 'object' || Array.isArray(raw)) {
    return { content: `record_screening returned an invalid response; persistence is uncertain. ${RECOVERY}`, isError: true };
  }
  const record = raw as Record<string, unknown>;
  if (typeof record.created !== 'boolean' || typeof record.id !== 'string' || !record.id ||
      !['passed', 'deferred', 'rejected', ''].includes(record.verdict as string) ||
      (record.screening_blocker !== undefined && typeof record.screening_blocker !== 'string') ||
      (record.verdict === '' && !['login_required', 'unreadable', 'not_found', 'expired'].includes(record.screening_blocker as string))) {
    return { content: `record_screening returned an invalid record; persistence is uncertain. ${RECOVERY}`, isError: true };
  }
  const blocker = (record.screening_blocker as string | undefined) ?? '';
  return { content: JSON.stringify({ id: record.id, verdict: record.verdict, screening_blocker: blocker,
    created: record.created, actionable: record.created && record.verdict === 'passed' && !blocker }), isError: false };
}

/** Evaluate once, record once, and expose only the server's authoritative record. */
export async function screenAndRecordPosting(
  args: Record<string, unknown>, adapter: ProviderAdapter | undefined, record: RecordScreeningCall | undefined,
): Promise<ScreenAndRecordResult> {
  const invalid = validateArgs(args);
  if (invalid) return { content: invalid, isError: true };
  if (!adapter) return { content: 'screen_and_record_posting is not configured: no screening provider adapter is available.', isError: true };
  if (!record) return { content: 'screen_and_record_posting cannot record: record_screening is not currently available.', isError: true };
  const screened = await screenPosting(args, adapter);
  if (screened.isError) return screened;
  let evidence: Record<string, unknown>;
  try { evidence = JSON.parse(screened.content) as Record<string, unknown>; } catch {
    return { content: 'screen_and_record_posting received invalid screening evidence; nothing was recorded.', isError: true };
  }
  const fields: Record<string, unknown> = {};
  for (const key of EVIDENCE_FIELDS) fields[key] = evidence[key];
  for (const key of ['url', 'role', 'company', 'profile', 'run_id', 'source', 'posted_date']) {
    if (args[key] !== undefined) fields[key] = args[key];
  }
  fields.posting_text = args.postingText;
  try {
    const persisted = await record(fields);
    if (persisted.isError) return { content: `record_screening failed (no actionable verdict): ${persisted.content}. ${RECOVERY}`, isError: true };
    return storedResult(persisted.content);
  } catch (err) {
    return { content: `record_screening transport failed (persistence uncertain): ${err instanceof Error ? err.message : String(err)}. ${RECOVERY}`, isError: true };
  }
}
