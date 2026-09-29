import { describe, expect, it, vi } from 'vitest';
import type { ProviderAdapter } from '../../providers/types.js';
import { screenAndRecordPosting } from '../screenAndRecordPosting.js';

const args = {
  url: 'https://example.org/jobs/17', role: 'Senior Engineer', company: 'Example Co',
  postingText: 'Senior engineering role, remote, working in English. Responsibilities include delivery and design.',
  profile: 'Engineering', criteria: 'Remote, English, permanent', run_id: 'run-7',
  source: 'feed', posted_date: '2026-09-22',
};
const proposal = {
  verdict: 'passed', screeningBlocker: '', failingCriterion: '', reason: 'matches',
  remoteArrangement: 'remote', languageRequirement: '', salaryStated: '',
  employmentCountryStated: 'Germany', roleTypeStated: 'permanent', eorStated: 'no',
};
function adapter(reply: string = JSON.stringify(proposal)) {
  const sendMessage = vi.fn(async function* () {
    yield { type: 'done' as const, stopReason: 'end' as const, message: { role: 'assistant' as const, content: reply } };
  });
  return { sendMessage } as ProviderAdapter & { sendMessage: typeof sendMessage };
}
function stored(overrides: Record<string, unknown> = {}) {
  return { content: JSON.stringify({ id: 'screen-17', created: true, verdict: 'passed', screening_blocker: '',
    posting_text: 'Full posting body '.repeat(3000), url: args.url, role: args.role, company: args.company,
    ...overrides }), isError: false };
}

describe('screenAndRecordPosting', () => {
  it('sends explicit producer-shaped evidence exactly once then returns the stored record', async () => {
    const provider = adapter();
    const record = vi.fn(async () => stored());
    const result = await screenAndRecordPosting(args, provider, record);
    expect(provider.sendMessage).toHaveBeenCalledTimes(1);
    expect(record).toHaveBeenCalledTimes(1);
    expect(record).toHaveBeenCalledWith({
      url: args.url, role: args.role, company: args.company, profile: args.profile, run_id: args.run_id,
      source: 'feed', posted_date: '2026-09-22', posting_text: args.postingText,
      verdict: 'passed', screening_blocker: '', failing_criterion: '', reason: 'matches',
      remote_arrangement: 'remote', language_requirement: '', salary_stated: '',
      employment_country_stated: 'Germany', role_type_stated: 'permanent', eor_stated: 'no',
    });
    expect(result.isError).toBe(false);
    expect(JSON.parse(result.content)).toEqual({ id: 'screen-17', created: true, verdict: 'passed', screening_blocker: '', actionable: true });
    expect(result.content).not.toContain('posting_text');
  });

  it('rejects missing metadata and caller-supplied verdict before model work', async () => {
    const provider = adapter();
    const record = vi.fn(async () => stored());
    for (const bad of [{ ...args, run_id: ' ' }, { ...args, url: 'file:///private/data' }, { ...args, verdict: 'passed' }]) {
      expect((await screenAndRecordPosting(bad, provider, record)).isError).toBe(true);
    }
    expect(provider.sendMessage).not.toHaveBeenCalled();
    expect(record).not.toHaveBeenCalled();
  });

  it('never writes if the adapter/tool is missing or the screening output is invalid', async () => {
    const record = vi.fn(async () => stored());
    expect((await screenAndRecordPosting(args, undefined, record)).isError).toBe(true);
    const provider = adapter();
    expect((await screenAndRecordPosting(args, provider, undefined)).isError).toBe(true);
    expect(provider.sendMessage).not.toHaveBeenCalled();
    const bad = adapter('not json');
    expect((await screenAndRecordPosting(args, bad, record)).isError).toBe(true);
    expect(record).not.toHaveBeenCalled();
  });

  it('treats the stored downgrade and duplicate as non-actionable, never the proposed pass', async () => {
    const provider = adapter();
    const record = vi.fn().mockResolvedValueOnce(stored({ verdict: 'rejected', failing_criterion: 'remote_model' }))
      .mockResolvedValueOnce(stored({ created: false, verdict: 'passed' }));
    const downgraded = JSON.parse((await screenAndRecordPosting(args, provider, record)).content);
    const duplicate = JSON.parse((await screenAndRecordPosting(args, provider, record)).content);
    expect(downgraded).toMatchObject({ verdict: 'rejected', actionable: false });
    expect(downgraded).not.toHaveProperty('failing_criterion');
    expect(duplicate).toMatchObject({ created: false, verdict: 'passed', actionable: false });
    expect(record).toHaveBeenCalledTimes(2);
  });

  it('never treats a stored pass with a blocker as actionable', async () => {
    const result = await screenAndRecordPosting(args, adapter(), vi.fn(async () => stored({ screening_blocker: 'login_required' })));
    expect(result.isError).toBe(false);
    expect(JSON.parse(result.content)).toEqual({ id: 'screen-17', created: true, verdict: 'passed',
      screening_blocker: 'login_required', actionable: false });
  });

  it('requires operator ledger review before manual recovery on uncertain persistence', async () => {
    const result = await screenAndRecordPosting(args, adapter(), vi.fn(async () => ({ content: '{bad', isError: false })));
    expect(result.isError).toBe(true);
    expect(result.content).toContain('GET /api/screenings');
    expect(result.content).toContain("JSON array's url fields");
    expect(result.content).toContain('this posting URL');
    expect(result.content).toContain('/screenings UI does not display URLs');
    expect(result.content).toContain('not the entire run');
    expect(result.content).toContain('continue other work and coverage');
    expect(result.content).toContain('operator confirms no record exists');
  });

  it('reports rejected persistence, malformed responses and transport failures without retrying', async () => {
    const provider = adapter();
    const record = vi.fn().mockResolvedValueOnce({ content: 'profile invalid', isError: true })
      .mockResolvedValueOnce({ content: '{bad json', isError: false })
      .mockRejectedValueOnce(new Error('connection closed'));
    for (let i = 0; i < 3; i++) {
      const result = await screenAndRecordPosting(args, provider, record);
      expect(result.isError).toBe(true);
      expect(result.content).not.toContain('"actionable":true');
    }
    expect(record).toHaveBeenCalledTimes(3);
    expect(provider.sendMessage).toHaveBeenCalledTimes(3);
  });
});
