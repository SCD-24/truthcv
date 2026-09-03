import { describe, it, expect } from 'vitest';
import { execFile } from 'node:child_process';
import http from 'node:http';
import path from 'node:path';

const SCRIPT = path.resolve(__dirname, '../agent-config.js');
const MAX_BUFFER = 16 * 1024 * 1024;

interface RunResult {
  status: number | null;
  stdout: string;
}

/**
 * Run agent-config.js for one field, capturing stdout through a pipe exactly
 * as daily-apply.sh and supervisor.js do. `fake` sets FAKE_AGENT_CONFIG,
 * `mcpUrl` sets TRUTHCV_MCP_URL; either is unset when omitted so the test
 * never inherits a real one from the environment. Async (not spawnSync) so
 * an in-test HTTP server on the same event loop can answer the child.
 */
function runConfig(field: string, opts: { fake?: string; mcpUrl?: string } = {}): Promise<RunResult> {
  const env: NodeJS.ProcessEnv = { ...process.env };
  delete env.TRUTHCV_MCP_URL;
  delete env.FAKE_AGENT_CONFIG;
  if (opts.fake !== undefined) env.FAKE_AGENT_CONFIG = opts.fake;
  if (opts.mcpUrl !== undefined) env.TRUTHCV_MCP_URL = opts.mcpUrl;
  return new Promise((resolve) => {
    const child = execFile(
      process.execPath,
      [SCRIPT, field],
      { encoding: 'utf8', maxBuffer: MAX_BUFFER, env },
      (_err, stdout) => resolve({ status: child.exitCode, stdout }),
    );
  });
}

/** Serve `body` as JSON on a loopback port; resolves to the base URL. */
function serveJson(body: string): Promise<{ url: string; close: () => void }> {
  return new Promise((resolve) => {
    const server = http.createServer((_req, res) => {
      res.writeHead(200, { 'Content-Type': 'application/json' });
      res.end(body);
    });
    server.listen(0, '127.0.0.1', () => {
      const addr = server.address() as { port: number };
      resolve({ url: `http://127.0.0.1:${addr.port}/mcp`, close: () => server.close() });
    });
  });
}

describe('agent-config.js — stdout is drained before exit', () => {
  // The payload is served over HTTP rather than via FAKE_AGENT_CONFIG: a
  // single environment variable of this size exceeds Linux's per-argument
  // limit (128 KB) and spawn fails with E2BIG before the script even runs.
  it('emits a >256 KB job_config payload without truncation', async () => {
    const PROFILE_COUNT = 300;
    const profiles = Array.from({ length: PROFILE_COUNT }, (_, i) => ({
      id: `profile-${i}`,
      enabled: true,
      description: 'x'.repeat(1024),
    }));
    // Mirrors the keys the job_config branch emits, in order.
    const expectedPayload = {
      profiles,
      targetCompanies: [],
      cooldownDays: 30,
      cooldownDaysSameRole: undefined,
      cooldownDaysSameCompany: undefined,
      maxApplicationsPerRun: undefined,
      maxPostingAgeDays: undefined,
      companyBoards: [],
      searchQueries: [],
      feedPostings: [],
      feedError: '',
      directBoards: [],
    };
    const expected = JSON.stringify(expectedPayload);
    expect(expected.length).toBeGreaterThan(256 * 1024);

    const server = await serveJson(JSON.stringify({ profiles, cooldownDays: 30 }));
    try {
      const res = await runConfig('job_config', { mcpUrl: server.url });
      expect(res.status).toBe(0);
      expect(res.stdout.length).toBe(expected.length);
      expect(res.stdout).toBe(expected);
      expect(JSON.parse(res.stdout).profiles.length).toBe(PROFILE_COUNT);
    } finally {
      server.close();
    }
  });

  it('prints the fake mode and exits 0', async () => {
    const res = await runConfig('mode', { fake: JSON.stringify({ mode: 'shadow' }) });
    expect(res.status).toBe(0);
    expect(res.stdout).toBe('shadow');
  });

  it('exits 1 with empty stdout for an unknown field and no TRUTHCV_MCP_URL', async () => {
    const res = await runConfig('bogus');
    expect(res.status).toBe(1);
    expect(res.stdout).toBe('');
  });
});
