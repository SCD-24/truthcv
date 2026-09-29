/**
 * Compose a stage's STATIC system prompt from prompt.md sections plus RUNBOOK
 * sections named in stages.ts. Deliberately contains no date, run id or
 * counts, so the text is byte-identical across runs and prompt-cacheable.
 */
import { existsSync } from 'node:fs';
import { dirname, join, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';
import { readRunbookSection } from '../builtins/readRunbook.js';
import { STAGES, type StageName } from '../stages.js';

/** Separator between composed sections. */
const SECTION_SEPARATOR = '\n\n';

/** Locate the agent directory (the one holding RUNBOOK.md), from src or dist. */
export function defaultAgentDir(): string {
  const here = dirname(fileURLToPath(import.meta.url));
  for (const rel of ['../..', '../../..']) {
    const dir = resolve(here, rel);
    if (existsSync(join(dir, 'RUNBOOK.md'))) return dir;
  }
  return resolve(here, '../..');
}

/** Fetch named sections from one markdown file; throws on an unknown heading. */
async function sectionsFrom(path: string, names: readonly string[]): Promise<string[]> {
  const out: string[] = [];
  for (const section of names) {
    const res = await readRunbookSection({ section }, path);
    if (res.isError) throw new Error(`stage prompt section '${section}' not found in ${path}`);
    out.push(res.content);
  }
  return out;
}

/**
 * Build the static system prompt for `stage`.
 *
 * @param stage Registered stage name.
 * @param agentDir Directory holding prompt.md and RUNBOOK.md.
 */
export async function composeStagePrompt(stage: StageName, agentDir: string = defaultAgentDir()): Promise<string> {
  const def = STAGES[stage];
  const prompt = await sectionsFrom(join(agentDir, 'prompt.md'), def.promptSections ?? []);
  const runbook = await sectionsFrom(join(agentDir, 'RUNBOOK.md'), def.runbookSections ?? []);
  return [...prompt, ...runbook].join(SECTION_SEPARATOR);
}
