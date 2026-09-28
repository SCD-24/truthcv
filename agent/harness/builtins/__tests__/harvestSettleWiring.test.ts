import { describe, expect, it } from 'vitest';
import { harvestPostings } from '../harvestPostings.js';
import type { BrowserToolCall } from '../harvestTypes.js';

describe('settle wiring', () => {
  it('waits out a loading searchUrl board and classifies the later snapshot', async () => {
    let snapshots = 0;
    const call: BrowserToolCall = async (name) => {
      if (name === 'browser_snapshot') {
        snapshots++;
        const content = snapshots === 1
          ? '- heading "Finding jobs..."'
          : [
            '- Page URL: https://acme.example/search',
            '- link "Senior Backend Engineer" [ref=e1]: https://jobs.lever.co/acme/one',
            '- link "Staff Data Scientist" [ref=e2]: https://jobs.lever.co/acme/two',
          ].join('\n');
        return { content, isError: false };
      }
      return { content: 'ok', isError: false };
    };
    const result = await harvestPostings(
      { boards: [{ board: 'Acme', url: 'https://acme.example/x', searchUrl: 'https://acme.example/search?q={keywords}', keywords: 'go' }] },
      call,
      false,
    );
    expect(JSON.parse(result.content).results[0].outcome).toBe('searched');
  });
});
