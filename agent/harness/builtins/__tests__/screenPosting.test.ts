import { describe, it, expect } from 'vitest';

import type { HarnessEvent, ProviderAdapter } from '../../providers/types.js';
import { screenPosting } from '../screenPosting.js';

/** A stub {@link ProviderAdapter} that yields exactly the given script once. */
function stubAdapter(script: HarnessEvent[]): ProviderAdapter {
  return {
    async *sendMessage() {
      for (const event of script) yield event;
    },
  };
}

/** A stub adapter whose `sendMessage` throws instead of yielding. */
function throwingAdapter(message: string): ProviderAdapter {
  return {
    // eslint-disable-next-line require-yield
    async *sendMessage() {
      throw new Error(message);
    },
  };
}

/** A stub adapter that yields a different scripted event list on each
 * successive call — the last script repeats once `scripts` is exhausted. */
function sequencedAdapter(scripts: HarnessEvent[][]): ProviderAdapter {
  let call = 0;
  return {
    async *sendMessage() {
      const script = scripts[Math.min(call, scripts.length - 1)];
      call += 1;
      for (const event of script) yield event;
    },
  };
}

/** A `done` event carrying the given assistant text. */
function doneWith(text: string): HarnessEvent {
  return { type: 'done', stopReason: 'end', message: { role: 'assistant', content: text } };
}

const VALID_ARGS = {
  url: 'https://example.com/jobs/1',
  role: 'Senior Engineer',
  company: 'Example Corp',
  postingText: 'We are hiring a senior engineer, fully remote, English required.',
  profile: 'Backend (Remote)',
  criteria: 'remote_model: remote\nworking_language: English',
};

const VALID_VERDICT_JSON = JSON.stringify({
  verdict: 'passed',
  screeningBlocker: '',
  failingCriterion: '',
  reason: 'Matches remote and language criteria.',
  remoteArrangement: 'remote',
  languageRequirement: '',
  salaryStated: '',
  employmentCountryStated: '',
  roleTypeStated: '',
  eorStated: '',
});

describe('screenPosting', () => {
  it('returns a structured verdict from a stubbed adapter, keyed for record_screening', async () => {
    const adapter = stubAdapter([doneWith(VALID_VERDICT_JSON)]);

    const result = await screenPosting(VALID_ARGS, adapter);

    expect(result.isError).toBe(false);
    // record_screening (agenttools/tools_ledger.py) takes snake_case
    // arguments; the isolated screening model's own reply is camelCase (see
    // VALID_VERDICT_JSON), but the JSON handed back to the calling model must
    // already be renamed onto record_screening's own argument names so it can
    // be passed straight through.
    expect(JSON.parse(result.content)).toEqual({
      verdict: 'passed',
      screening_blocker: '',
      failing_criterion: '',
      reason: 'Matches remote and language criteria.',
      remote_arrangement: 'remote',
      language_requirement: '',
      salary_stated: '',
      employment_country_stated: '',
      role_type_stated: '',
      eor_stated: '',
    });
  });

  it('emits exactly the snake_case keys record_screening expects', async () => {
    const adapter = stubAdapter([doneWith(VALID_VERDICT_JSON)]);

    const result = await screenPosting(VALID_ARGS, adapter);

    const keys = Object.keys(JSON.parse(result.content)).sort();
    expect(keys).toEqual(
      [
        'failing_criterion',
        'language_requirement',
        'reason',
        'remote_arrangement',
        'screening_blocker',
        'verdict',
        'salary_stated',
        'employment_country_stated',
        'role_type_stated',
        'eor_stated',
      ].sort(),
    );
  });

  it('reports a screening_blocker verdict with no verdict set', async () => {
    const blockerJson = JSON.stringify({
      verdict: '',
      screeningBlocker: 'login_required',
      failingCriterion: '',
      reason: 'Posting sat behind a sign-in wall.',
      remoteArrangement: '',
      languageRequirement: '',
    });
    const adapter = stubAdapter([doneWith(blockerJson)]);

    const result = await screenPosting(VALID_ARGS, adapter);

    expect(result.isError).toBe(false);
    const verdict = JSON.parse(result.content);
    expect(verdict.verdict).toBe('');
    expect(verdict.screening_blocker).toBe('login_required');
  });

  it('never throws on a provider error event, and returns isError', async () => {
    const adapter = stubAdapter([{ type: 'error', message: 'upstream 500', retryable: true }]);

    const result = await screenPosting(VALID_ARGS, adapter);

    expect(result.isError).toBe(true);
    expect(result.content).toContain('upstream 500');
  });

  it('never throws when sendMessage itself throws', async () => {
    const adapter = throwingAdapter('socket hang up');

    const result = await screenPosting(VALID_ARGS, adapter);

    expect(result.isError).toBe(true);
    expect(result.content).toContain('socket hang up');
  });

  it('rejects a reply that is not well-formed JSON', async () => {
    const adapter = stubAdapter([doneWith('not json at all')]);

    const result = await screenPosting(VALID_ARGS, adapter);

    expect(result.isError).toBe(true);
    expect(result.content).toContain('did not return a valid verdict');
  });

  it('rejects a reply with neither a verdict nor a screeningBlocker', async () => {
    const json = JSON.stringify({
      verdict: '',
      screeningBlocker: '',
      failingCriterion: '',
      reason: '',
      remoteArrangement: '',
      languageRequirement: '',
    });
    const adapter = stubAdapter([doneWith(json)]);

    const result = await screenPosting(VALID_ARGS, adapter);

    expect(result.isError).toBe(true);
  });

  it('rejects a reply with an unrecognised verdict value', async () => {
    const json = JSON.stringify({
      verdict: 'maybe',
      screeningBlocker: '',
      failingCriterion: '',
      reason: '',
      remoteArrangement: '',
      languageRequirement: '',
    });
    const adapter = stubAdapter([doneWith(json)]);

    const result = await screenPosting(VALID_ARGS, adapter);

    expect(result.isError).toBe(true);
  });

  it('parses a reply missing the screeningBlocker and remoteArrangement keys', async () => {
    const sparseJson = JSON.stringify({
      verdict: 'passed',
      failingCriterion: '',
      reason: 'Matches remote and language criteria.',
      languageRequirement: '',
    });
    const adapter = stubAdapter([doneWith(sparseJson)]);

    const result = await screenPosting(VALID_ARGS, adapter);

    expect(result.isError).toBe(false);
    const verdict = JSON.parse(result.content);
    expect(verdict.verdict).toBe('passed');
    expect(verdict.screening_blocker).toBe('');
    expect(verdict.remote_arrangement).toBe('');
  });

  it('parses the four new stated-evidence fields when present', async () => {
    const json = JSON.stringify({
      verdict: 'passed',
      screeningBlocker: '',
      failingCriterion: '',
      reason: 'Matches every criterion.',
      remoteArrangement: 'remote',
      languageRequirement: '',
      salaryStated: '$120k-140k',
      employmentCountryStated: 'Germany',
      roleTypeStated: 'contract',
      eorStated: 'yes',
    });
    const adapter = stubAdapter([doneWith(json)]);

    const result = await screenPosting(VALID_ARGS, adapter);

    expect(result.isError).toBe(false);
    const verdict = JSON.parse(result.content);
    expect(verdict.salary_stated).toBe('$120k-140k');
    expect(verdict.employment_country_stated).toBe('Germany');
    expect(verdict.role_type_stated).toBe('contract');
    expect(verdict.eor_stated).toBe('yes');
  });

  it('defaults the four new stated-evidence fields to \'\' when missing', async () => {
    const sparseJson = JSON.stringify({
      verdict: 'passed',
      failingCriterion: '',
      reason: 'Matches remote and language criteria.',
      languageRequirement: '',
    });
    const adapter = stubAdapter([doneWith(sparseJson)]);

    const result = await screenPosting(VALID_ARGS, adapter);

    expect(result.isError).toBe(false);
    const verdict = JSON.parse(result.content);
    expect(verdict.salary_stated).toBe('');
    expect(verdict.employment_country_stated).toBe('');
    expect(verdict.role_type_stated).toBe('');
    expect(verdict.eor_stated).toBe('');
  });

  it('defaults the four new stated-evidence fields to \'\' when non-string', async () => {
    const json = JSON.stringify({
      verdict: 'passed',
      screeningBlocker: '',
      failingCriterion: '',
      reason: 'Matches every criterion.',
      remoteArrangement: 'remote',
      languageRequirement: '',
      salaryStated: 12345,
      employmentCountryStated: null,
      roleTypeStated: true,
      eorStated: {},
    });
    const adapter = stubAdapter([doneWith(json)]);

    const result = await screenPosting(VALID_ARGS, adapter);

    expect(result.isError).toBe(false);
    const verdict = JSON.parse(result.content);
    expect(verdict.salary_stated).toBe('');
    expect(verdict.employment_country_stated).toBe('');
    expect(verdict.role_type_stated).toBe('');
    expect(verdict.eor_stated).toBe('');
  });

  it("normalises an unrecognised eorStated value ('probably') to ''", async () => {
    const json = JSON.stringify({
      verdict: 'passed',
      screeningBlocker: '',
      failingCriterion: '',
      reason: 'Matches every criterion.',
      remoteArrangement: 'remote',
      languageRequirement: '',
      eorStated: 'probably',
    });
    const adapter = stubAdapter([doneWith(json)]);

    const result = await screenPosting(VALID_ARGS, adapter);

    expect(result.isError).toBe(false);
    const verdict = JSON.parse(result.content);
    expect(verdict.eor_stated).toBe('');
  });

  it("normalises a wrong-case eorStated value ('Yes') the same way remoteArrangement does", async () => {
    const json = JSON.stringify({
      verdict: 'passed',
      screeningBlocker: '',
      failingCriterion: '',
      reason: 'Matches every criterion.',
      remoteArrangement: 'remote',
      languageRequirement: '',
      eorStated: 'Yes',
    });
    const adapter = stubAdapter([doneWith(json)]);

    const result = await screenPosting(VALID_ARGS, adapter);

    expect(result.isError).toBe(false);
    const verdict = JSON.parse(result.content);
    expect(verdict.eor_stated).toBe('');
  });

  it('parses a reply wrapped in a ```json code fence', async () => {
    const fenced = '```json\n' + VALID_VERDICT_JSON + '\n```';
    const adapter = stubAdapter([doneWith(fenced)]);

    const result = await screenPosting(VALID_ARGS, adapter);

    expect(result.isError).toBe(false);
    expect(JSON.parse(result.content).verdict).toBe('passed');
  });

  it('retries once after a provider error, succeeding on the second call', async () => {
    const adapter = sequencedAdapter([
      [{ type: 'error', message: 'upstream 500', retryable: true }],
      [doneWith(VALID_VERDICT_JSON)],
    ]);

    const result = await screenPosting(VALID_ARGS, adapter);

    expect(result.isError).toBe(false);
    expect(JSON.parse(result.content).verdict).toBe('passed');
  });

  it('returns isError after two consecutive provider errors', async () => {
    let calls = 0;
    const adapter: ProviderAdapter = {
      async *sendMessage() {
        calls += 1;
        yield { type: 'error', message: 'upstream 500', retryable: true };
      },
    };

    const result = await screenPosting(VALID_ARGS, adapter);

    expect(result.isError).toBe(true);
    expect(result.content).toContain('upstream 500');
    expect(calls).toBe(2);
  });

  it('never calls the provider when a required argument is missing', async () => {
    let called = false;
    const adapter: ProviderAdapter = {
      async *sendMessage() {
        called = true;
        yield doneWith(VALID_VERDICT_JSON);
      },
    };

    const { url: _url, ...withoutUrl } = VALID_ARGS;
    const result = await screenPosting(withoutUrl, adapter);

    expect(result.isError).toBe(true);
    expect(result.content).toContain('url');
    expect(called).toBe(false);
  });

  it('lists every missing required field by name', async () => {
    const adapter = stubAdapter([doneWith(VALID_VERDICT_JSON)]);

    const result = await screenPosting({}, adapter);

    expect(result.isError).toBe(true);
    for (const field of ['url', 'role', 'company', 'postingText', 'profile', 'criteria']) {
      expect(result.content).toContain(field);
    }
  });
});
