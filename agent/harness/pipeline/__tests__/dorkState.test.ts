import { describe, expect, it } from 'vitest';
import { defaultDorkState, loadDorkState, saveDorkState, type DorkStateFs } from '../dorkState.js';

function memFs(initial?: string): { fs: DorkStateFs; files: Map<string, string> } {
  const files = new Map<string, string>();
  if (initial !== undefined) files.set('s.json', initial);
  const fs: DorkStateFs = {
    readFileText: async (p) => {
      const v = files.get(p);
      if (v === undefined) throw new Error('ENOENT');
      return v;
    },
    writeFileText: async (p, t) => void files.set(p, t),
    renameFile: async (a, b) => {
      files.set(b, files.get(a) ?? '');
      files.delete(a);
    },
  };
  return { fs, files };
}

describe('dorkState', () => {
  it('returns defaults when the file is missing', async () => {
    expect(await loadDorkState('s.json', memFs().fs)).toEqual(defaultDorkState());
  });
  it('returns defaults when the file is corrupt', async () => {
    expect(await loadDorkState('s.json', memFs('{nope').fs)).toEqual(defaultDorkState());
    expect(await loadDorkState('s.json', memFs('null').fs)).toEqual(defaultDorkState());
  });
  it('sanitizes bad field types', async () => {
    const s = await loadDorkState('s.json', memFs('{"lastSearchAt":"x","deferred":[1,"a"],"cooldownUntil":5}').fs);
    expect(s).toEqual({ lastSearchAt: 0, consecutiveBlocks: 0, cooldownUntil: 5, deferred: ['a'] });
  });
  it('round-trips a saved state', async () => {
    const { fs } = memFs();
    const state = { lastSearchAt: 100, consecutiveBlocks: 1, cooldownUntil: 900, deferred: ['g: q'] };
    expect(await saveDorkState('s.json', state, fs)).toBeUndefined();
    expect(await loadDorkState('s.json', fs)).toEqual(state);
  });
  it('writes via a temp file renamed over the target', async () => {
    const { fs, files } = memFs();
    const writes: string[] = [];
    const w = fs.writeFileText;
    fs.writeFileText = async (p, t) => { writes.push(p); await w(p, t); };
    await saveDorkState('s.json', defaultDorkState(), fs);
    expect(writes).toEqual(['s.json.tmp']);
    expect([...files.keys()]).toEqual(['s.json']);
  });
  it('reports a rename failure', async () => {
    const { fs } = memFs();
    fs.renameFile = async () => { throw new Error('busy'); };
    expect(await saveDorkState('s.json', defaultDorkState(), fs)).toContain('busy');
  });
  it('treats out-of-range times as absent', async () => {
    const s = await loadDorkState('s.json', memFs('{"lastSearchAt":1e300,"cooldownUntil":8.64e15,"deferred":[]}').fs);
    expect(s.lastSearchAt).toBe(0);
    expect(s.cooldownUntil).toBe(8.64e15);
    expect(() => new Date(s.cooldownUntil).toISOString()).not.toThrow();
    const t = await loadDorkState('s.json', memFs('{"cooldownUntil":8.64e15001}').fs);
    expect(t.cooldownUntil).toBe(0);
  });
  it('reports a save failure instead of throwing', async () => {
    const fs: DorkStateFs = { readFileText: async () => '', writeFileText: async () => { throw new Error('disk full'); }, renameFile: async () => {} };
    expect(await saveDorkState('s.json', defaultDorkState(), fs)).toContain('disk full');
  });
});
