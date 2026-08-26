import { describe, it, expect } from 'vitest';
import { namespaceTool, namespaceTools } from '../nameTransform.js';

describe('namespaceTool', () => {
  it('joins server and tool with a double underscore', () => {
    expect(namespaceTool('truthcv', 'record_application')).toBe('truthcv__record_application');
  });

  it('sanitises invalid characters to underscores', () => {
    expect(namespaceTool('serv.er', 'tool/name!')).toBe('serv_er__tool_name_');
  });

  it('truncates an over-long name to <=64 chars with an 8-hex-char hash suffix', () => {
    const out = namespaceTool('srv', 'x'.repeat(80));
    expect(out.length).toBeLessThanOrEqual(64);
    expect(out).toMatch(/-[0-9a-f]{8}$/);
  });

  it('keeps two long names that share a truncated prefix distinguishable', () => {
    const shared = 'a'.repeat(70);
    const one = namespaceTool('srv', `${shared}ONE`);
    const two = namespaceTool('srv', `${shared}TWO`);
    expect(one).not.toBe(two);
    expect(one.length).toBeLessThanOrEqual(64);
    expect(two.length).toBeLessThanOrEqual(64);
  });
});

describe('namespaceTools', () => {
  it('disambiguates pairs that sanitise to the same name', () => {
    const map = namespaceTools([
      { serverName: 'srv', toolName: 'a.b' },
      { serverName: 'srv', toolName: 'a/b' },
    ]);
    expect(map.size).toBe(2);
    expect(new Set(map.keys()).size).toBe(2);
    for (const name of map.keys()) expect(name.length).toBeLessThanOrEqual(64);
  });

  it('maps each unique name back to its source pair', () => {
    const map = namespaceTools([{ serverName: 'browser', toolName: 'browser_navigate' }]);
    expect(map.get('browser__browser_navigate')).toEqual({ serverName: 'browser', toolName: 'browser_navigate' });
  });
});
