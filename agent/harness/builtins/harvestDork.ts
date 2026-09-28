/**
 * Google `site:` dork handling for `harvest_postings` — recognises a Google
 * search-results page whose query targets a site, and extracts the result
 * links pointing at that site.
 */

import { hostsRelated, stripHash, type ResolvedLink } from './harvestLinks.js';
import type { HarvestedPosting } from './harvestTypes.js';

/** A dork's `site:` target. `pathPrefix` is `''` when no path was given. */
export interface DorkTarget {
  host: string;
  pathPrefix: string;
}

/** Google search hosts: google.<tld> or www.google.<tld>. */
const GOOGLE_HOST_RE = /^(?:www\.)?google\.[a-z]{2,3}(?:\.[a-z]{2})?$/i;

/** Hosts owned by Google, never a dork result. */
const GOOGLE_OWNED_RE = /(?:^|\.)(?:google\.[a-z.]+|gstatic\.com|googleusercontent\.com|googleapis\.com)$/i;

/** First `site:` token in a query. */
const SITE_TOKEN_RE = /(?:^|\s)site:(\S+)/i;

/** A URL scheme prefix. */
const SCHEME_RE = /^[a-z][a-z0-9+.-]*:\/\//i;

/** Cap on dork postings returned. */
const MAX_DORK_POSTINGS = 50;

/** Parse a Google search URL's `site:` target, or null when not a dork. */
export function parseDorkTarget(pageUrl: string): DorkTarget | null {
  let url: URL;
  try {
    url = new URL(pageUrl);
  } catch {
    return null;
  }
  if (!GOOGLE_HOST_RE.test(url.hostname) || url.pathname !== '/search') return null;
  const token = SITE_TOKEN_RE.exec(url.searchParams.get('q') ?? '');
  if (!token) return null;
  const bare = token[1].replace(SCHEME_RE, '').toLowerCase();
  const slash = bare.indexOf('/');
  const host = slash === -1 ? bare : bare.slice(0, slash);
  if (host === '') return null;
  const pathPrefix = slash === -1 ? '' : bare.slice(slash).replace(/\/+$/, '');
  return { host, pathPrefix };
}

/** Unwrap a `google.<tld>/url?q=<target>` redirect; else return `href`. */
export function unwrapGoogleRedirect(href: URL): URL {
  if (!GOOGLE_HOST_RE.test(href.hostname) || href.pathname !== '/url') return href;
  const target = href.searchParams.get('q') ?? href.searchParams.get('url');
  if (!target) return href;
  try {
    return new URL(target);
  } catch {
    return href;
  }
}

/** Whether `url` is a result for `target`. */
function matchesTarget(url: URL, target: DorkTarget): boolean {
  if (GOOGLE_OWNED_RE.test(url.hostname)) return false;
  if (!hostsRelated(url.hostname, target.host)) return false;
  const path = url.pathname.toLowerCase().replace(/\/+$/, '');
  if (path === target.pathPrefix) return false;
  return target.pathPrefix === '' || path.startsWith(`${target.pathPrefix}/`);
}

/** Extract links pointing at the dork's `site:` target, deduped. */
export function extractDorkPostings(links: ResolvedLink[], target: DorkTarget): HarvestedPosting[] {
  const seen = new Set<string>();
  const postings: HarvestedPosting[] = [];
  for (const link of links) {
    const url = unwrapGoogleRedirect(link.url);
    if (!matchesTarget(url, target)) continue;
    const key = stripHash(url.href);
    if (seen.has(key)) continue;
    seen.add(key);
    postings.push({ url: key, title: link.title.trim(), ats: 'dork-site' });
    if (postings.length >= MAX_DORK_POSTINGS) break;
  }
  return postings;
}
