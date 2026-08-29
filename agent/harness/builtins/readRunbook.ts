/**
 * The harness's one and only built-in tool: `read_runbook_section`.
 *
 * The agent's operating spec, agent/RUNBOOK.md, is large (~40KB). Rather than
 * pin the whole thing in every prompt, the system/first-turn prompt carries
 * only the non-negotiable rules and a table of contents; the detailed
 * procedure for each phase of work is fetched on demand, one named section at
 * a time, through this tool.
 *
 * This tool reads EXACTLY ONE fixed file — the RUNBOOK — and exposes no
 * file-path argument, so it opens no path-traversal surface and grants no
 * general filesystem-read capability. It is deliberately NOT MCP-backed: the
 * MCP allow-list in tools.ts remains the harness's only authorization boundary
 * over its MCP tool surface, and this narrow exception sits entirely outside
 * it.
 */

import { readFile } from 'node:fs/promises';
import type { ToolDefinition } from '../providers/types.js';

/**
 * The result shape this handler returns. Mirrors the MCP pool's
 * `ToolCallResult` (`{ content, isError }`): the caller in tools.ts attaches
 * the `toolCallId` and caps the content, exactly as it does for MCP results.
 */
export interface RunbookToolResult {
  /** The requested section's text, or an error message. */
  content: string;
  /** True when the section was not found or the RUNBOOK could not be read. */
  isError: boolean;
}

/** A parsed RUNBOOK heading: its depth (2 for `##`, 3 for `###`), title and line. */
interface Heading {
  /** Heading depth: 2 for `##`, 3 for `###`. */
  level: number;
  /** The heading text with the leading `#` markers and surrounding space stripped. */
  text: string;
  /** Zero-based index of the heading line within the split file. */
  lineIndex: number;
}

/** Matches a `##` or `###` heading line, capturing its markers and title text. */
const HEADING_RE = /^(#{2,3})\s+(.*)$/;

/**
 * The provider-facing definition advertised to the model. Its single argument,
 * `section`, is a required string naming the heading to fetch (matched
 * case-insensitively and with surrounding whitespace trimmed). No path
 * argument is accepted or exposed.
 */
export const readRunbookSectionTool: ToolDefinition = {
  name: 'read_runbook_section',
  description:
    "Return the full text of one named section of your operating spec (RUNBOOK.md). " +
    'The RUNBOOK is not inlined in the prompt — the system/first-turn prompt carries only ' +
    'the non-negotiable rules and a table of contents (the section headings). Call this tool ' +
    'to fetch the detailed procedure for a section BEFORE starting each phase of work, passing ' +
    'the heading title as `section` (matched case-insensitively, surrounding whitespace ignored). ' +
    'If the section name is not recognised, the error result lists every valid section name.',
  inputSchema: {
    type: 'object',
    properties: {
      section: {
        type: 'string',
        description:
          "The heading title of the RUNBOOK section to fetch, e.g. '4. Truthfulness rules — " +
          "non-negotiable'. Matched case-insensitively against the RUNBOOK's ## / ### headings, " +
          'with surrounding whitespace trimmed.',
      },
    },
    required: ['section'],
    additionalProperties: false,
  },
};

/**
 * Parse the RUNBOOK into its `##` / `###` headings, in document order.
 */
function parseHeadings(lines: string[]): Heading[] {
  const headings: Heading[] = [];
  for (let i = 0; i < lines.length; i++) {
    const m = HEADING_RE.exec(lines[i]);
    if (!m) continue;
    headings.push({ level: m[1].length, text: m[2].trim(), lineIndex: i });
  }
  return headings;
}

/**
 * Fetch one named section of the RUNBOOK.
 *
 * Pure and path-parameterised: the file path is passed in (defaulted by the
 * caller, never hardcoded here) so tests can point it at a fixture. Reads the
 * file, splits it on `##` / `###` headings, and returns the matched section's
 * full text (heading line included), where a section runs from its heading
 * until the next heading of the same-or-shallower level — so a `##` section
 * includes its `###` subsections, while a `###` request returns just that
 * subsection.
 *
 * Never throws: a missing/unreadable file, or an unknown section name, is
 * returned as an `isError` result the model can read and recover from.
 *
 * @param args The requested `section` heading title.
 * @param runbookPath Absolute path to the RUNBOOK.md file to read.
 * @returns The section text, or an error message, with `isError` set.
 */
export async function readRunbookSection(
  args: { section: string },
  runbookPath: string,
): Promise<RunbookToolResult> {
  let raw: string;
  try {
    raw = await readFile(runbookPath, 'utf8');
  } catch (err) {
    const message = err instanceof Error ? err.message : String(err);
    return {
      content: `RUNBOOK.md could not be read at ${runbookPath}: ${message}`,
      isError: true,
    };
  }

  const lines = raw.split('\n');
  const headings = parseHeadings(lines);
  const wanted = args.section.trim().toLowerCase();

  const idx = headings.findIndex((h) => h.text.toLowerCase() === wanted);
  if (idx === -1) {
    const valid = headings.map((h) => h.text).join(', ');
    return {
      content: `Unknown section '${args.section}'. Valid sections: ${valid}`,
      isError: true,
    };
  }

  const start = headings[idx];
  // The section ends at the next heading of the same-or-shallower level (so a
  // `##` section keeps its `###` subsections), or at end-of-file.
  const next = headings.find((h, j) => j > idx && h.level <= start.level);
  const endLine = next ? next.lineIndex : lines.length;
  const content = lines.slice(start.lineIndex, endLine).join('\n').replace(/\s+$/, '');

  return { content, isError: false };
}
