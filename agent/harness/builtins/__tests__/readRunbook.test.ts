import { describe, it, expect, beforeAll, afterAll } from 'vitest';
import { mkdtempSync, rmSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { readRunbookSection, readRunbookSectionTool } from '../readRunbook.js';

/**
 * A small RUNBOOK-shaped fixture: a top-level title (ignored by the parser),
 * three `##` sections with distinct headings and body text, plus one `###`
 * subsection nested under the second `##` to exercise level-aware bounds.
 */
const FIXTURE = [
  '# Fixture spec',
  '',
  'Preamble text that belongs to no section.',
  '',
  '## Alpha section',
  '',
  'Body of alpha.',
  '',
  '## Beta Section',
  '',
  'Body of beta before the subsection.',
  '',
  '### Beta detail',
  '',
  'Body of the beta detail subsection.',
  '',
  '## Gamma — final',
  '',
  'Body of gamma.',
  '',
].join('\n');

let dir: string;
let runbookPath: string;

beforeAll(() => {
  dir = mkdtempSync(join(tmpdir(), 'runbook-test-'));
  runbookPath = join(dir, 'RUNBOOK.md');
  writeFileSync(runbookPath, FIXTURE, 'utf8');
});

afterAll(() => {
  rmSync(dir, { recursive: true, force: true });
});

describe('readRunbookSectionTool definition', () => {
  it('is named read_runbook_section and requires exactly the string arg `section`', () => {
    expect(readRunbookSectionTool.name).toBe('read_runbook_section');
    const schema = readRunbookSectionTool.inputSchema as {
      properties: Record<string, { type: string }>;
      required: string[];
      additionalProperties: boolean;
    };
    expect(schema.required).toEqual(['section']);
    expect(schema.properties.section.type).toBe('string');
    expect(schema.additionalProperties).toBe(false);
    // No file-path argument is exposed.
    expect(Object.keys(schema.properties)).toEqual(['section']);
  });
});

describe('readRunbookSection', () => {
  it('returns a section body verbatim (heading line included) for an exact-case match', async () => {
    const result = await readRunbookSection({ section: 'Alpha section' }, runbookPath);
    expect(result.isError).toBe(false);
    expect(result.content).toBe('## Alpha section\n\nBody of alpha.');
  });

  it('matches a heading case-insensitively and ignoring surrounding whitespace', async () => {
    const result = await readRunbookSection({ section: '  gAmMa — final  ' }, runbookPath);
    expect(result.isError).toBe(false);
    expect(result.content).toBe('## Gamma — final\n\nBody of gamma.');
  });

  it('includes nested ### subsections when a ## section is requested', async () => {
    const result = await readRunbookSection({ section: 'Beta Section' }, runbookPath);
    expect(result.isError).toBe(false);
    // The `## Beta Section` runs until the next same-or-shallower heading
    // (`## Gamma`), so it carries its `### Beta detail` subsection with it.
    expect(result.content).toContain('## Beta Section');
    expect(result.content).toContain('Body of beta before the subsection.');
    expect(result.content).toContain('### Beta detail');
    expect(result.content).toContain('Body of the beta detail subsection.');
    expect(result.content).not.toContain('Gamma');
  });

  it('returns just the ### subsection when the subsection heading is requested', async () => {
    const result = await readRunbookSection({ section: 'Beta detail' }, runbookPath);
    expect(result.isError).toBe(false);
    expect(result.content).toBe('### Beta detail\n\nBody of the beta detail subsection.');
  });

  it('returns isError and lists every real section name for an unknown section', async () => {
    const result = await readRunbookSection({ section: 'Does not exist' }, runbookPath);
    expect(result.isError).toBe(true);
    expect(result.content).toContain("Unknown section 'Does not exist'");
    for (const name of ['Alpha section', 'Beta Section', 'Beta detail', 'Gamma — final']) {
      expect(result.content).toContain(name);
    }
  });

  it('returns isError without throwing when the file does not exist', async () => {
    const missing = join(dir, 'no-such-RUNBOOK.md');
    const result = await readRunbookSection({ section: 'Alpha section' }, missing);
    expect(result.isError).toBe(true);
    expect(result.content).toContain('RUNBOOK.md could not be read at');
    expect(result.content).toContain(missing);
  });
});
