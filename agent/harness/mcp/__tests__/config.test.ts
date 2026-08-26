import { describe, it, expect } from 'vitest';
import { fileURLToPath } from 'node:url';
import { dirname, resolve } from 'node:path';
import { expandPlaceholders, loadMcpConfig } from '../config.js';

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
