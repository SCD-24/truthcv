/**
 * Prune a Playwright MCP accessibility snapshot down to the posting's plain
 * text: page chrome (banner, navigation, footer, language pickers, asides)
 * and structural noise (refs, urls, roles) are removed. Pure and deterministic.
 */

/** Roles whose whole subtree is page chrome. */
export const DROPPED_ROLES = ['banner', 'navigation', 'complementary', 'contentinfo', 'combobox', 'listbox'] as const;

/** Name of the generic footer container. */
const FOOTER_NAME = 'footer';

/** Name of the search-filters region. */
const SEARCH_FILTERS_NAME = 'search filters';

/** Heading level used when the snapshot gives none. */
const DEFAULT_HEADING_LEVEL = 2;

/** Page title header line. */
const TITLE_RE = /^- Page Title:\s*(.*)$/;

/** Other header lines and code fences. */
const HEADER_RE = /^(?:(?:### Page|### Snapshot|```\w*)\s*$|- (?:Page URL|Console):)/;

/** A `- /url:` child line. */
const URL_LINE_RE = /^\s*-\s*\/url:/;

/** Playwright attribute tokens (`[expanded]`, `[ref=e1]`, `[pressed=true]`) stripped from every kept line; case-sensitive so quoted names like `[Remote]` survive. */
const TOKEN_RE = /\s*\[[a-z][a-z-]*(?:=[^\]]*)?\]/g;

/** Heading level token. */
const LEVEL_RE = /\[level=(\d+)\]/;

/** `- role "name": value` shape (name and value optional). */
const NODE_RE = /^-\s*([^\s:"]+)(?:\s+"((?:[^"\\]|\\.)*)")?\s*(?::\s*(.*))?$/;

interface Node {
  role: string;
  name: string;
  value: string;
}

function indentOf(line: string): number {
  return line.length - line.trimStart().length;
}

function parseNode(body: string): Node | null {
  const m = NODE_RE.exec(body.replace(TOKEN_RE, '').trim());
  return m ? { role: m[1].toLowerCase(), name: m[2] ?? '', value: (m[3] ?? '').trim() } : null;
}

function isDropped(node: Node): boolean {
  const name = node.name.toLowerCase();
  if ((DROPPED_ROLES as readonly string[]).includes(node.role)) return true;
  if (node.role === 'generic') return name === FOOTER_NAME;
  return node.role === 'region' && name === SEARCH_FILTERS_NAME;
}

function flatten(node: Node, raw: string): string {
  const joined = [node.name, node.value].filter(Boolean).join(' ');
  if (joined === '') return '';
  if (node.role === 'heading') {
    const level = Number(LEVEL_RE.exec(raw)?.[1] ?? DEFAULT_HEADING_LEVEL);
    return `${'#'.repeat(level)} ${joined}`;
  }
  return node.role === 'listitem' || node.role === 'text' ? `- ${joined}` : joined;
}

/**
 * Reduce a raw snapshot to `Title: …` plus the posting's plain text lines.
 *
 * @param snapshot Raw Playwright MCP snapshot text.
 */
export function pruneSnapshot(snapshot: string): string {
  const out: string[] = [];
  let skipBelow = -1;
  for (const line of snapshot.split('\n')) {
    const title = TITLE_RE.exec(line);
    if (title) { out.push(`Title: ${title[1].trim()}`); continue; }
    if (HEADER_RE.test(line) || URL_LINE_RE.test(line) || line.trim() === '') continue;
    const indent = indentOf(line);
    if (skipBelow >= 0 && indent > skipBelow) continue;
    skipBelow = -1;
    const node = parseNode(line.trim());
    if (node && isDropped(node)) { skipBelow = indent; continue; }
    const text = node ? flatten(node, line) : line.trim();
    if (text !== '' && text !== out[out.length - 1]) out.push(text);
  }
  return out.join('\n').trim();
}
