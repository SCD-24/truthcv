/**
 * Scheme allow-list for anything rendered as a clickable href. Data reaching
 * these call sites can come from agent/scraped sources (company research
 * findings, job-posting URLs), not just operator typing, so a `javascript:`
 * or other unexpected-scheme value must never reach a live `href` — it would
 * execute in the operator's authenticated session on click.
 */
const ALLOWED_SCHEMES = new Set(["http:", "https:", "mailto:", "tel:"]);

/**
 * Return a safe href for `raw`, or `null` if it must not be rendered as a
 * live link. A value with no scheme at all is treated as a bare host and
 * gets `https://` prepended (matching how operators type "example.com").
 * A value with an explicit scheme is only accepted if that scheme is
 * allow-listed; anything else (javascript:, data:, vbscript:, file:, …)
 * is rejected outright.
 */
export function safeHref(raw: string): string | null {
  const trimmed = raw.trim();
  if (!trimmed) return null;
  const schemeMatch = /^([a-z][a-z0-9+.-]*):/i.exec(trimmed);
  if (!schemeMatch) return `https://${trimmed}`;
  const scheme = schemeMatch[1].toLowerCase() + ":";
  return ALLOWED_SCHEMES.has(scheme) ? trimmed : null;
}
