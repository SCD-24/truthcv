/**
 * Pure link-parsing/resolution primitives for `harvest_postings` extraction
 * — split out of harvestClassify.ts so that module can stay focused on
 * classification/tier selection. Understands BOTH accessibility-tree link
 * shapes Playwright's real `browser_snapshot` output uses: the same-line
 * form (`- link "Title" [ref=eN]: https://…`) and the indented-child form
 * (`- link "Title" [ref=eN] [cursor=pointer]:` followed by a child
 * `  - /url: <href>` line, often a RELATIVE href that must be resolved
 * against the snapshot's own `- Page URL: <url>` line, or the board's `url`
 * when no such line is present).
 */

import type { HarvestBoardRequest } from './harvestTypes.js';

/** One link parsed from a snapshot, with its href not yet resolved. */
interface RawLink {
  title: string;
  href: string;
}

/** One link with its href resolved to an absolute http(s) URL. */
export interface ResolvedLink {
  title: string;
  url: URL;
}

/** Matches a link line's leading indent, accessible-name title, and
 * whatever follows the closing quote (which may itself hold a same-line
 * URL). */
const LINK_TAG_RE = /^(\s*)-\s*link\s+"([^"]+)"(.*)$/;

/** Matches an http(s) URL anywhere in a same-line link's trailing text. */
const HTTP_URL_RE = /https?:\/\/\S+/;

/** Matches a Playwright child `- /url: <href>` line. */
const CHILD_URL_RE = /^\s*-\s*\/url:\s*(\S+)/;

/** Matches the snapshot's own `- Page URL: <url>` line, used as the base
 * for resolving a relative child href. Anchored to a line start so an
 * earlier paragraph merely mentioning "- Page URL:" inline can't win. */
const PAGE_URL_RE = /^\s*-\s*Page URL:\s*(\S+)/im;

/** Strip trailing punctuation a same-line URL match tends to pick up
 * (closing parens, sentence-ending commas/periods). */
function cleanUrl(raw: string): string {
  return raw.replace(/[).,]+$/, '');
}

/** Find the resolved href from an indented `- /url: …` child of the link
 * line at `parentIndent`, scanning forward only while later lines remain
 * more indented than the parent (i.e. still its descendants). */
function findChildUrl(lines: string[], start: number, parentIndent: number): string | undefined {
  for (let j = start; j < lines.length; j++) {
    if (lines[j].trim() === '') continue;
    const indent = (lines[j].match(/^(\s*)/) as RegExpMatchArray)[1].length;
    if (indent <= parentIndent) return undefined;
    const urlMatch = lines[j].match(CHILD_URL_RE);
    if (urlMatch) return cleanUrl(urlMatch[1]);
  }
  return undefined;
}

/** Parse one link, if any, starting at `lines[i]` — same-line URL first,
 * falling back to a Playwright indented `- /url:` child line. */
function parseLinkAt(lines: string[], i: number): RawLink | undefined {
  const m = lines[i].match(LINK_TAG_RE);
  if (!m) return undefined;
  const [, indent, title, rest] = m;
  const sameLine = rest.match(HTTP_URL_RE);
  if (sameLine) return { title, href: cleanUrl(sameLine[0]) };
  const href = findChildUrl(lines, i + 1, indent.length);
  return href ? { title, href } : undefined;
}

/** Parse every link line in `snapshot`, in document order, hrefs not yet
 * resolved to absolute URLs. */
export function parseSnapshotLinks(snapshot: string): RawLink[] {
  const lines = snapshot.split('\n');
  const results: RawLink[] = [];
  for (let i = 0; i < lines.length; i++) {
    const link = parseLinkAt(lines, i);
    if (link) results.push(link);
  }
  return results;
}

/** The base URL to resolve a relative href against: the snapshot's own
 * `- Page URL: <url>` line if present, else `board.url`. */
export function resolveSnapshotBase(board: HarvestBoardRequest, snapshot: string): string {
  const m = snapshot.match(PAGE_URL_RE);
  return m ? m[1] : board.url;
}

/** Resolve one href against `base`, dropping anything non-http(s) or
 * unparsable. */
function resolveHref(href: string, base: string): URL | undefined {
  try {
    const url = new URL(href, base);
    return url.protocol === 'http:' || url.protocol === 'https:' ? url : undefined;
  } catch {
    return undefined;
  }
}

/** Parse and resolve every link in `snapshot` to an absolute http(s) URL,
 * dropping any that are non-http(s) or fail to parse even against the
 * resolved base. */
export function resolveLinks(board: HarvestBoardRequest, snapshot: string): ResolvedLink[] {
  const base = resolveSnapshotBase(board, snapshot);
  const resolved: ResolvedLink[] = [];
  for (const link of parseSnapshotLinks(snapshot)) {
    const url = resolveHref(link.href, base);
    if (url) resolved.push({ title: link.title, url });
  }
  return resolved;
}

/** Strip a URL's fragment, so two links differing only by `#…` compare equal. */
export function stripHash(url: string): string {
  return url.split('#')[0];
}

/** Convert a board's simple posting-link glob (`*` as the only wildcard)
 * into an anchored, open-ended `RegExp` — e.g. `https://boards.example.com/job/*`
 * matches any URL starting with that literal prefix, `*` standing in for any
 * non-space run. Case-SENSITIVE outside the wildcards, per the glob spec
 * (only `*` is special); `URL.href` already lowercases scheme/host, so a
 * lowercase host in the pattern still matches a real URL's href. */
export function globToRegExp(pattern: string): RegExp {
  const escapeRegex = (s: string): string => s.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
  const parts = pattern.split('*').map(escapeRegex);
  return new RegExp('^' + parts.join('\\S*'));
}

/** Whether hostnames `a` and `b` are the same site: equal, or one a
 * subdomain of the other. */
export function hostsRelated(a: string, b: string): boolean {
  if (a === b) return true;
  return a.endsWith(`.${b}`) || b.endsWith(`.${a}`);
}

/** Minimum hyphen-separated tokens a path segment needs to itself look
 * like a posting slug (e.g. `senior-backend-engineer`), absent any digit. */
const MIN_HYPHEN_TOKENS = 3;

/** Known job-listing path segment names, English and German. */
const JOB_PATH_SEGMENT_RE = /^(jobs?|stellen?(angebote?)?|stellenanzeige|positions?|vacanc(y|ies)|careers?|job-?offers?|offers?)$/i;

/** Matches a pagination segment (`page`, `page-2`, `page/3`'s `page`,
 * `seite`, `seite-2`, …), English and German — never a posting slug. */
const PAGE_SEITE_RE = /^(page|seite)[-_]?\d*$/i;

/** Whether `segment` (a path segment AFTER a job-listing segment) itself
 * looks like a specific posting's slug: a digit, or ≥3 hyphenated tokens —
 * but never a bare pagination segment like `page-2` or `seite`. */
function segmentQualifies(segment: string): boolean {
  if (PAGE_SEITE_RE.test(segment)) return false;
  return /\d/.test(segment) || segment.split('-').filter(Boolean).length >= MIN_HYPHEN_TOKENS;
}

/** Whether `pathname` has a job-listing segment (e.g. `/jobs/`) followed by
 * a LATER segment that itself looks like one specific posting. A segment
 * directly following a pagination segment (e.g. the `3` in `/jobs/page/3`)
 * never counts, even if it's numeric. */
export function hasJobPath(pathname: string): boolean {
  const segments = pathname.split('/').filter(Boolean);
  for (let i = 0; i < segments.length; i++) {
    if (!JOB_PATH_SEGMENT_RE.test(segments[i])) continue;
    for (let j = i + 1; j < segments.length; j++) {
      if (PAGE_SEITE_RE.test(segments[j - 1])) continue;
      if (segmentQualifies(segments[j])) return true;
    }
  }
  return false;
}

/** Whether `title`, trimmed, is purely digits — never a real posting title. */
export function isNumericTitle(title: string): boolean {
  return /^\d+$/.test(title.trim());
}

/** Minimum trimmed title length for the same-site heuristic to trust a
 * link's accessible name as a real posting title. */
export const MIN_TITLE_LENGTH = 4;

/**
 * Whether `link` qualifies as a same-site job-listing link: same site as
 * `baseHost` (equal or one a subdomain of the other), a job-listing path
 * segment followed by a segment that looks like one specific posting, its
 * hash-stripped URL not equal to any of `excludeHrefs` (the base/board
 * URLs themselves), and a plausible non-numeric title.
 */
export function sameSiteLinkQualifies(link: ResolvedLink, baseHost: string, excludeHrefs: ReadonlySet<string>): boolean {
  if (!hostsRelated(link.url.hostname, baseHost)) return false;
  if (!hasJobPath(link.url.pathname)) return false;
  if (excludeHrefs.has(stripHash(link.url.href))) return false;
  const title = link.title.trim();
  return title.length >= MIN_TITLE_LENGTH && !isNumericTitle(title);
}
