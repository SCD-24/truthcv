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
    });
  });

  it('emits exactly the snake_case keys record_screening expects', async () => {
    const adapter = stubAdapter([doneWith(VALID_VERDICT_JSON)]);

    const result = await screenPosting(VALID_ARGS, adapter);

    const keys = Object.keys(JSON.parse(result.content)).sort();
    expect(keys).toEqual(
      ['failing_criterion', 'language_requirement', 'reason', 'remote_arrangement', 'screening_blocker', 'verdict'].sort(),
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
