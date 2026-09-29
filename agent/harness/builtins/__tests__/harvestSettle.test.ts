import { describe, expect, it } from 'vitest';
import { settleIfLoading } from '../harvestNavigate.js';
import type { BrowserToolCall } from '../harvestTypes.js';

function stub(snapshots: Array<{ content: string; isError: boolean }>): { call: BrowserToolCall; names: string[] } {
  const names: string[] = [];
  let i = 0;
  const call: BrowserToolCall = async (name) => {
    names.push(name);
    if (name === 'browser_snapshot') return snapshots[Math.min(i++, snapshots.length - 1)];
    return { content: 'ok', isError: false };
  };
  return { call, names };
}

const ok = (content: string) => ({ content, isError: false });

describe('settleIfLoading', () => {
  it('makes no calls when not loading', async () => {
    const { call, names } = stub([]);
    expect(await settleIfLoading(call, 'all done')).toBe('all done');
    expect(names).toEqual([]);
  });
  it('ignores posting titles containing Loading', async () => {
    const { call, names } = stub([]);
    await settleIfLoading(call, '- link "Loading Dock Manager" [ref=e1]:\n  - /url: https://a.example/1');
    expect(names).toEqual([]);
  });
  it('resolves on first retry', async () => {
    const { call, names } = stub([ok('results ready')]);
    expect(await settleIfLoading(call, 'Finding jobs...')).toBe('results ready');
    expect(names.filter((n) => n === 'browser_wait_for')).toHaveLength(1);
  });
  it('waits at most five times when still loading', async () => {
    const { call, names } = stub([ok('Loading...')]);
    await settleIfLoading(call, 'Loading...');
    expect(names.filter((n) => n === 'browser_wait_for')).toHaveLength(5);
  });
  it('exits early once the page clears', async () => {
    const { call, names } = stub([ok('Loading...'), ok('Loading...'), ok('results ready')]);
    expect(await settleIfLoading(call, 'Loading...')).toBe('results ready');
    expect(names.filter((n) => n === 'browser_wait_for')).toHaveLength(3);
  });
  it('returns previous snapshot on snapshot error', async () => {
    const { call } = stub([{ content: 'boom', isError: true }]);
    expect(await settleIfLoading(call, 'Loading...')).toBe('Loading...');
  });
});
