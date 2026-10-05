/**
 * Finds the "onward" link on an intermediate job page (e.g. an Adzuna
 * `/land/ad/` page whose real posting sits behind "Weitere Informationen ❯"),
 * so fetchPosting can follow it once. Pure: parses a raw snapshot only.
 */
import { isSignInUrl } from '../builtins/harvestNavigate.js';
import { normaliseLabel, ONWARD_LABELS, parseSnapshotLinks } from '../builtins/harvestLinks.js';

/** Matches the snapshot's own `- Page URL: <url>` line. */
const PAGE_URL_LINE_RE = /^\s*-\s*Page URL:\s*(\S+)/im;

/** Link paths never followed onward (application flows). */
const APPLY_URL_RE =
  /\/(?:apply|application|applications|bewerben|bewerbung|login|signin|sign-in|register|auth)(?:[-_.][^/?#]*)?(?=[/?#]|$)/i;

/** Link labels that indicate an application or sign-in flow. */
const APPLY_LABEL_RE = /\b(?:apply|application|bewerb\w*|log\s?in|sign\s?-?in|register)/i;

/** Resolve `href` against `base`; `undefined` when not a http(s) URL. */
function resolveHttp(href: string, base: string): string | undefined {
  try {
    const url = new URL(href, base);
    return url.protocol === 'http:' || url.protocol === 'https:' ? url.href : undefined;
  } catch {
    return undefined;
  }
}

/**
 * The absolute URL of the first onward link in `snapshot`, or `undefined`.
 * Never returns an apply or sign-in link.
 *
 * @param snapshot Raw snapshot text.
 * @param currentUrl URL navigated to (fallback base for relative hrefs).
 */
export function findOnwardUrl(snapshot: string, currentUrl: string): string | undefined {
  const base = snapshot.match(PAGE_URL_LINE_RE)?.[1] ?? currentUrl;
  for (const link of parseSnapshotLinks(snapshot)) {
    if (!ONWARD_LABELS.includes(normaliseLabel(link.title))) continue;
    if (APPLY_LABEL_RE.test(link.title)) continue;
    const target = resolveHttp(link.href, base);
    if (target && !APPLY_URL_RE.test(target) && !isSignInUrl(target)) return target;
  }
  return undefined;
}
