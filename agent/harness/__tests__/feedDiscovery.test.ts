import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { describe, expect, it, vi } from 'vitest';

import type { McpClientPool, NamespacedTool } from '../mcp/client.js';
import { runLoop } from '../loop.js';
import type { ConversationMessage, HarnessEvent, ProviderAdapter, ToolCall } from '../providers/types.js';

const feedUrl = 'https://boards.greenhouse.io/feedco/jobs/123456';
const boardUrl = 'https://example.com/direct-jobs';
const fullText = 'Senior Engineer: remote, English required. Full responsibilities and requirements.';
const feedCall = (id: string, url = feedUrl): ToolCall => ({
  id, name: 'screen_and_record_posting', arguments: {
    url, role: 'Senior Engineer', company: 'FeedCo', postingText: fullText,
    profile: 'Backend', criteria: 'remote_model: remote', run_id: 'run-1', source: 'greenhouse',
  },
});
const harvestCall: ToolCall = { id: 'harvest', name: 'harvest_postings',
  arguments: { boards: [{ board: 'DirectCo', url: boardUrl }] } };
const event = (...toolCalls: ToolCall[]): HarnessEvent => ({ type: 'done', stopReason: 'toolCalls',
  message: { role: 'assistant', content: '', toolCalls } });
const end: HarnessEvent = { type: 'done', stopReason: 'end', message: { role: 'assistant', content: 'done' } };

function adapter(scripts: HarnessEvent[]): ProviderAdapter {
  let turn = 0;
  return { async *sendMessage() { yield scripts[Math.min(turn++, scripts.length - 1)]; } };
}

function pool(record: (args: Record<string, unknown>) => { content: string; isError: boolean }) {
  const names = ['truthcv__record_screening', 'browser__browser_navigate', 'browser__browser_snapshot'];
  const tools: NamespacedTool[] = names.map((namespacedName) => {
    const [serverName, toolName] = namespacedName.split('__');
    return { namespacedName, serverName, toolName, description: '', inputSchema: { type: 'object' } };
  });
  const calls: { name: string; args: Record<string, unknown> }[] = [];
  const client = { listTools: () => tools, refreshTools: vi.fn(async () => {}),
    callTool: vi.fn(async (name: string, args: Record<string, unknown>) => {
      calls.push({ name, args });
      if (name === 'truthcv__record_screening') return record(args);
      if (name === 'browser__browser_navigate') return { content: 'ok', isError: false };
      if (name === 'browser__browser_snapshot') return {
        content: '- link "Engineer" [ref=e1]: https://jobs.lever.co/directco/role-1', isError: false,
      };
      throw new Error(`Unexpected tool: ${name}`);
    }),
  } as unknown as McpClientPool;
  return { client, calls };
}

const screeningAdapter = adapter([{ type: 'done', stopReason: 'end', message: { role: 'assistant',
  content: JSON.stringify({ verdict: 'passed', screeningBlocker: '', failingCriterion: '',
    reason: 'remote and English', remoteArrangement: 'remote', languageRequirement: 'English' }) } }]);

async function run(scripts: HarnessEvent[], client: McpClientPool) {
  const initialMessages: ConversationMessage[] = [{ role: 'user', content: 'feed first, then direct' }];
  return runLoop({ adapter: adapter(scripts), screeningAdapter, pool: client, systemPrompt: 'follow the runbook',
    initialMessages, config: { maxTurns: 8 }, sleep: async () => {} });
}

describe('feed discovery ordering', () => {
  it('documents save-before-harvest, no double recording and strict actionable/duplicate behavior', () => {
    const prompt = readFileSync(fileURLToPath(new URL('../../prompt.md', import.meta.url)), 'utf8');
    const runbook = readFileSync(fileURLToPath(new URL('../../RUNBOOK.md', import.meta.url)), 'utf8');
    const readme = readFileSync(fileURLToPath(new URL('../../README.md', import.meta.url)), 'utf8');
    for (const text of [prompt, runbook, readme]) {
      expect(text).toContain('GET /api/screenings');
      expect(text).toMatch(/JSON\s+array's `url`\s+fields/);
      expect(text).toContain('not the entire run');
      expect(text).toContain('operator confirms no record exists');
    }
    for (const text of [prompt, runbook]) {
      expect(text).toContain('screen_and_record_posting');
      expect(text).toContain('harvest_postings');
      expect(text).toMatch(/feed[\s\S]*direct boards/);
      expect(text).toMatch(/created:false[\s\S]*skip/);
    }
    expect(prompt).toMatch(/screen and SAVE it with[\s\S]*before direct boards/);
    expect(prompt).toContain('Only `actionable:true`');
    expect(prompt).toContain('no `screening_blocker`');
  });

  it('persists feed full text before scripted direct-board harvest, preserving channel sources', async () => {
    const stderr = vi.spyOn(process.stderr, 'write').mockImplementation(() => true);
    try {
      const { client, calls } = pool((args) => ({ content: JSON.stringify({
        id: 'saved-1', created: true, verdict: 'passed', screening_blocker: '',
        posting_text: args.posting_text,
      }), isError: false }));
      const result = await run([event(feedCall('feed')), event(harvestCall), end], client);
      const outputs = result.messages.filter((m) => m.role === 'tool').flatMap((m) => m.toolResults ?? []);
      expect(result.stopReason).toBe('end');
      expect(outputs.map((o) => o.toolCallId)).toEqual(['feed', 'harvest']);
      expect(JSON.parse(outputs[0].content)).toMatchObject({ id: 'saved-1', actionable: true });
      const harvested = JSON.parse(outputs[1].content).results[0];
      expect(harvested).toMatchObject({ board: 'DirectCo', outcome: 'searched' });
      expect(harvested.postings[0].url).toBe('https://jobs.lever.co/directco/role-1');
      expect(calls.map((c) => c.name)).toEqual([
        'truthcv__record_screening', 'browser__browser_navigate', 'browser__browser_snapshot',
      ]);
      expect(calls[0].args).toMatchObject({ source: 'greenhouse', url: feedUrl, posting_text: fullText });
      expect(calls[1].args).toMatchObject({ url: boardUrl });
      expect(calls.some((c) => c.name === 'truthcv__record_screening' && c.args.url === harvested.postings[0].url)).toBe(false);
    } finally { stderr.mockRestore(); }
  });

  it('preserves the first feed save when the next save fails, continuing later discovery without retrying', async () => {
    let n = 0;
    const { client, calls } = pool(() => ++n === 1
      ? { content: JSON.stringify({ id: 'saved-1', created: true, verdict: 'passed' }), isError: false }
      : { content: 'failed', isError: true });
    const result = await run([event(feedCall('first')), event(feedCall('second', `${feedUrl}-2`)), event(harvestCall), end], client);
    const outputs = result.messages.filter((m) => m.role === 'tool').flatMap((m) => m.toolResults ?? []);
    expect(outputs.map((o) => o.toolCallId)).toEqual(['first', 'second', 'harvest']);
    expect(JSON.parse(outputs[0].content)).toMatchObject({ id: 'saved-1', actionable: true });
    expect(outputs[1].isError).toBe(true);
    expect(outputs[1].content).toContain('GET /api/screenings');
    expect(outputs[1].content).toContain('not the entire run');
    expect(JSON.parse(outputs[2].content).results[0].outcome).toBe('searched');
    expect(calls.map((c) => c.name)).toEqual([
      'truthcv__record_screening', 'truthcv__record_screening',
      'browser__browser_navigate', 'browser__browser_snapshot',
    ]);
    expect(calls.slice(0, 2).map((c) => c.args.source)).toEqual(['greenhouse', 'greenhouse']);
  });
});
