import { describe, expect, it } from 'vitest';
import { harvestPostings } from '../harvestPostings.js';
import type { BrowserToolCall } from '../harvestTypes.js';

const BUDGET = 24000;
const BOARD_COUNT = 8;

describe('harvestPostings result budget', () => {
  it('keeps all boards within the budget', async () => {
    const big = '- generic "filler": some results text here\n'.repeat(1000);
    const call: BrowserToolCall = async (name) => ({ content: name === 'browser_snapshot' ? big : 'ok', isError: false });
    const boards = Array.from({ length: BOARD_COUNT }, (_, i) => ({ board: `b${i}`, url: `https://b${i}.example/jobs` }));
    const result = await harvestPostings({ boards }, call, false, undefined, undefined, BUDGET);
    expect(result.content.length).toBeLessThanOrEqual(BUDGET);
    expect(JSON.parse(result.content).results).toHaveLength(BOARD_COUNT);
  });
});
