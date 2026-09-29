/**
 * Role/company values a screening_blocker record can carry, derived from a
 * harvest title and posting URL, and guaranteed to pass record_screening's
 * placeholder validation (screening/role.py, screening/company.py).
 */

/** Role recorded on a blocker when the harvest title is unusable (record_screening rejects placeholders). */
export const BLOCKER_ROLE_FALLBACK = 'Unreadable posting';
/** Company recorded on a blocker when the URL has no usable hostname. */
export const BLOCKER_COMPANY_FALLBACK = 'Unidentified employer';
/** Max title length record_screening accepts as a role (screening/role.py). */
const MAX_ROLE_CHARS = 120;
/** Separator punctuation stripped from the ends of a title (screening/role.py `_SEPARATORS`). */
const EDGE_SEPARATORS = /^[-–—|·,:;\s]+|[-–—|·,:;\s]+$/g;

/** Placeholder titles record_screening rejects. Mirrors `_BOARD_NOISE` in screening/role.py; keep in sync. */
export const ROLE_BOARD_NOISE: ReadonlySet<string> = new Set([
  'apply', 'apply now', 'view job', 'view details', 'save job', 'job', 'jobs', 'position', 'vacancy',
  'n/a', 'na', 'none', 'unknown', 'tbd', 'see posting', 'see description',
  'full time', 'full-time', 'part time', 'part-time', 'remote', 'hybrid', 'onsite', 'on-site',
]);

/** Placeholder employers record_screening rejects. Mirrors `_PLACEHOLDERS` in screening/company.py; keep in sync. */
export const COMPANY_PLACEHOLDERS: ReadonlySet<string> = new Set([
  'n/a', 'na', 'none', 'null', 'unknown', 'tbd', 'company', 'the company', 'employer', 'confidential',
  'undisclosed', 'not stated', 'not specified', 'see posting', 'see description', 'various', '-', '--',
]);

/** ATS hosts whose first URL path segment is the tenant (e.g. boards.greenhouse.io/acme/jobs/1). */
const PATH_TENANT_HOST = /^(?:(?:job-)?boards(?:\.eu)?\.greenhouse\.io|jobs(?:\.eu)?\.lever\.co|jobs\.ashbyhq\.com|apply\.workable\.com|(?:jobs|careers)\.smartrecruiters\.com)$/;
/** ATS domains whose subdomain is the tenant (e.g. acme.recruitee.com, acme.jobs.personio.de). */
const SUBDOMAIN_TENANT_HOST = /^([a-z0-9-]+)\.(?:recruitee\.com|(?:jobs\.)?personio\.(?:de|com)|teamtailor\.com|(?:wd\d+\.)?myworkdayjobs\.com|bamboohr\.com|breezy\.hr|workable\.com|jobs\.workable\.com)$/;
/** Generic host prefixes dropped when falling back to the hostname. */
const HOST_PREFIX = /^(?:www|jobs|careers|boards|job-boards|apply)\./;

/** Collapse whitespace and strip edge separators (role.py `normalize_role_title`). */
function normalizeText(text: string): string {
  return text.replace(/\s+/g, ' ').replace(EDGE_SEPARATORS, '').trim();
}

/** A role a blocker record can carry: the normalized harvest title when record_screening would accept it. */
export function roleForBlocker(title: string): string {
  const t = normalizeText(title);
  const bad = !t || t.includes('://') || t.startsWith('www.') || t.length > MAX_ROLE_CHARS
    || !/[A-Za-z]/.test(t) || ROLE_BOARD_NOISE.has(t.toLowerCase());
  return bad ? BLOCKER_ROLE_FALLBACK : t;
}

/** A tenant slug as a company name, or undefined when unusable. */
function usableCompany(raw: string | undefined): string | undefined {
  const name = normalizeText(decodeURIComponent(raw ?? '').replace(/[-_]+/g, ' '));
  const ok = name && /[A-Za-z]/.test(name) && name.length <= MAX_ROLE_CHARS && !COMPANY_PLACEHOLDERS.has(name.toLowerCase());
  return ok ? name : undefined;
}

/** The ATS tenant named by a known multi-tenant host, if any. */
function atsTenant(url: URL): string | undefined {
  const host = url.hostname.toLowerCase();
  if (PATH_TENANT_HOST.test(host)) return usableCompany(url.pathname.split('/')[1]);
  const sub = SUBDOMAIN_TENANT_HOST.exec(host);
  return sub ? usableCompany(sub[1]) : undefined;
}

/** A company name a blocker record can carry: the ATS tenant, else the hostname minus common prefixes. */
export function companyFromUrl(url: string): string {
  try {
    const parsed = new URL(url);
    const host = parsed.hostname.toLowerCase().replace(HOST_PREFIX, '');
    return atsTenant(parsed) ?? (/[A-Za-z]/.test(host) ? host : BLOCKER_COMPANY_FALLBACK);
  } catch {
    return BLOCKER_COMPANY_FALLBACK;
  }
}
