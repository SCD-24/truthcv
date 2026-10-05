/**
 * Passes Google's cookie-consent interstitial (consent.google.<tld>) by
 * clicking its accept button, so a blocked dork can be retried. Never touches
 * the /sorry CAPTCHA page.
 */
import { isGoogleInterstitial } from '../builtins/harvestClassify.js';
import type { BrowserToolCall } from '../builtins/harvestTypes.js';

/** Host prefix of Google's consent page. */
const CONSENT_HOST_PREFIX = 'consent.';

/** Seconds to wait after clicking accept, for the redirect to settle. */
const CONSENT_SETTLE_SECONDS = 2;

/** Accept-button labels (English and German). */
const ACCEPT_LABEL_RE = /^(?:alle akzeptieren|accept all|ich stimme zu|i agree|alle annehmen)$/i;

/** A button line: `- button "Label" [ref=eN]`. */
const BUTTON_LINE_RE = /-\s*button\s+"([^"]+)"[^\n]*?\[ref=([^\]]+)]/gi;

/** Whether `url` is a consent.google.<tld> page (not the /sorry CAPTCHA). */
function isConsentUrl(url: string): boolean {
  try {
    return isGoogleInterstitial(url) && new URL(url).hostname.toLowerCase().startsWith(CONSENT_HOST_PREFIX);
  } catch {
    return false;
  }
}

/** The accept button's label and ref in `snapshot`, if present. */
function findAcceptButton(snapshot: string): { element: string; ref: string } | undefined {
  for (const m of snapshot.matchAll(BUTTON_LINE_RE)) {
    if (ACCEPT_LABEL_RE.test(m[1].trim())) return { element: m[1], ref: m[2] };
  }
  return undefined;
}

/**
 * Try to accept Google's consent dialog at `blockedUrl`.
 *
 * @param call Browser tool caller.
 * @param blockedUrl URL of the blocking page.
 * @returns True only when the accept button was clicked without error; false otherwise (never throws).
 */
export async function tryPassGoogleConsent(call: BrowserToolCall, blockedUrl: string): Promise<boolean> {
  if (!isConsentUrl(blockedUrl)) return false;
  try {
    const nav = await call('browser_navigate', { url: blockedUrl });
    if (nav.isError) return false;
    const snap = await call('browser_snapshot', {});
    if (snap.isError) return false;
    const pageUrl = snap.content.match(/^\s*-\s*Page URL:\s*(\S+)/im)?.[1];
    // Fail closed: click only when the snapshot proves we are still on the consent page.
    if (!pageUrl || !isConsentUrl(pageUrl)) return false;
    const button = findAcceptButton(snap.content);
    if (!button) return false;
    const click = await call('browser_click', button);
    if (click.isError) return false;
    await call('browser_wait_for', { time: CONSENT_SETTLE_SECONDS });
    return true;
  } catch {
    return false;
  }
}
