/**
 * Posting identity for dedupe, mirroring `screening.url.posting_dedupe_key`
 * (the key the server's filter_unscreened_urls uses): scheme/host case, a
 * trailing slash, a trailing apply segment, the fragment and tracking
 * parameters are ignored, and any linkedin.com subdomain's /jobs/view/<id>
 * collapses to one key.
 */

const LINKEDIN_HOST = 'linkedin.com';
const LINKEDIN_JOB_PATH = /^\/jobs\/view\/(?:[^/]+-)?(\d+)\/?$/;
const APPLICATION_SEGMENTS = new Set(['apply', 'application', 'applications', 'apply-now']);
const TRACKING_PARAMS = new Set(['gh_src', 'lever-origin', 'lever-source', 'ref', 'referrer', 'source', 'src', 'trk', 'trackingid']);

/** Path without one trailing slash and one trailing apply-ish segment. */
function cleanPath(pathname: string): string {
  let path = pathname.endsWith('/') ? pathname.slice(0, -1) : pathname;
  const idx = path.lastIndexOf('/');
  if (idx >= 0 && APPLICATION_SEGMENTS.has(path.slice(idx + 1).toLowerCase())) path = path.slice(0, idx);
  return path;
}

/** Query string without tracking parameters, sorted. */
function cleanQuery(u: URL): string {
  const kept = [...u.searchParams.entries()].filter(([k]) => !TRACKING_PARAMS.has(k.toLowerCase()) && !k.toLowerCase().startsWith('utm_'));
  kept.sort((a, b) => (a[0] === b[0] ? (a[1] < b[1] ? -1 : a[1] > b[1] ? 1 : 0) : a[0] < b[0] ? -1 : 1));
  return new URLSearchParams(kept).toString();
}

/**
 * Identity of the posting `url` points at; `''` when it resolves to no posting.
 * Never throws.
 *
 * @param url Posting URL.
 */
export function postingKey(url: string): string {
  let u: URL;
  try {
    u = new URL(url.trim());
  } catch {
    return '';
  }
  if (u.protocol !== 'http:' && u.protocol !== 'https:') return '';
  const host = u.hostname.toLowerCase();
  if (host === LINKEDIN_HOST || host.endsWith(`.${LINKEDIN_HOST}`)) {
    const m = LINKEDIN_JOB_PATH.exec(u.pathname);
    if (m) return `https://www.linkedin.com/jobs/view/${m[1]}`;
  }
  const query = cleanQuery(u);
  return `${u.protocol}//${u.host}${cleanPath(u.pathname)}${query ? `?${query}` : ''}`;
}
