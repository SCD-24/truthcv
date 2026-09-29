import { describe, it, expect } from 'vitest';
import { fileURLToPath } from 'node:url';
import { dirname, resolve } from 'node:path';
import { expandPlaceholders, loadMcpConfig, resolveBrowserSessionCount } from '../config.js';

const here = dirname(fileURLToPath(import.meta.url));
// this file lives at agent/harness/mcp/__tests__; mcp.json is at agent/mcp.json.
const mcpJsonPath = resolve(here, '../../../mcp.json');

describe('loadMcpConfig', () => {
  it('falls back to the default URL and honours env overrides', () => {
    const env = {
      TRUTHCV_MCP_URL: undefined,
      BROWSER_MCP_URL: 'http://custom-browser:9999/mcp',
    } as NodeJS.ProcessEnv;

    const servers = loadMcpConfig(mcpJsonPath, env);
    const byName = Object.fromEntries(servers.map((s) => [s.name, s.url]));

    expect(byName.truthcv).toBe('http://app:8080/mcp');
    expect(byName.browser).toBe('http://custom-browser:9999/mcp');
  });

  it('returns one entry per non-comment server', () => {
    const servers = loadMcpConfig(mcpJsonPath, {} as NodeJS.ProcessEnv);
    expect(servers.map((s) => s.name).sort()).toEqual(['browser', 'truthcv']);
  });

  it('parses the browser server allowedTools allow-list', () => {
    const servers = loadMcpConfig(mcpJsonPath, {} as NodeJS.ProcessEnv);
    const browser = servers.find((s) => s.name === 'browser');
    expect(browser?.allowedTools).toEqual(expect.arrayContaining(['browser_snapshot', 'browser_navigate']));
  });

  it('leaves allowedTools absent for a server that declares none (truthcv)', () => {
    const servers = loadMcpConfig(mcpJsonPath, {} as NodeJS.ProcessEnv);
    const truthcv = servers.find((s) => s.name === 'truthcv');
    expect(truthcv?.allowedTools).toBeUndefined();
    expect(Object.prototype.hasOwnProperty.call(truthcv, 'allowedTools')).toBe(false);
  });
});

describe('expandPlaceholders', () => {
  it('expands multiple placeholders in one string using env or defaults', () => {
    const env = { A: 'aval', B: '' } as NodeJS.ProcessEnv;
    const out = expandPlaceholders('${A:-da}/${B:-db}/${C:-dc}', env);
    expect(out).toBe('aval/db/dc');
  });

  it('treats an empty env value as unset and uses the default', () => {
    const env = { X: '' } as NodeJS.ProcessEnv;
    expect(expandPlaceholders('${X:-fallback}', env)).toBe('fallback');
  });
});

describe('resolveBrowserSessionCount', () => {
  it('falls back to the default (3) when unset', () => {
    expect(resolveBrowserSessionCount({} as NodeJS.ProcessEnv)).toBe(3);
  });

  it('falls back to the default when empty', () => {
    expect(resolveBrowserSessionCount({ AGENT_BROWSER_SESSIONS: '' } as NodeJS.ProcessEnv)).toBe(3);
  });

  it('falls back to the default when non-numeric', () => {
    expect(resolveBrowserSessionCount({ AGENT_BROWSER_SESSIONS: 'abc' } as NodeJS.ProcessEnv)).toBe(3);
  });

  it('falls back to the default when negative', () => {
    expect(resolveBrowserSessionCount({ AGENT_BROWSER_SESSIONS: '-1' } as NodeJS.ProcessEnv)).toBe(3);
  });

  it('honours 0 (disables the extra-session path) rather than falling back', () => {
    expect(resolveBrowserSessionCount({ AGENT_BROWSER_SESSIONS: '0' } as NodeJS.ProcessEnv)).toBe(0);
  });

  it('honours a well-formed positive value', () => {
    expect(resolveBrowserSessionCount({ AGENT_BROWSER_SESSIONS: '1' } as NodeJS.ProcessEnv)).toBe(1);
  });

  it("falls back to the default for '3.5' — /^\\d+$/ rejects any non-integer", () => {
    expect(resolveBrowserSessionCount({ AGENT_BROWSER_SESSIONS: '3.5' } as NodeJS.ProcessEnv)).toBe(3);
  });

  it('clamps a well-formed value above the cap (8) down to the cap', () => {
    expect(resolveBrowserSessionCount({ AGENT_BROWSER_SESSIONS: '300' } as NodeJS.ProcessEnv)).toBe(8);
  });

  it("falls back to the default for '1e9' — /^\\d+$/ rejects exponential notation, so this never reaches the clamp", () => {
    expect(resolveBrowserSessionCount({ AGENT_BROWSER_SESSIONS: '1e9' } as NodeJS.ProcessEnv)).toBe(3);
  });
});
