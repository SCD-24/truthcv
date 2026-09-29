/**
 * Location-field detection and local-language alias expansion for
 * `harvest_postings`' direct-board-location-control flow. Split out of
 * harvestPostings.ts; see that module's own doc for the tool's behaviour as
 * a whole, and harvestBoard.ts for how these pieces compose into one
 * board's harvest.
 */

/** Cap on how many location candidates (the board's own value plus its
 * local-language aliases) are ever tried for one board — bounds the extra
 * browser round-trips a location-control retry costs. */
export const MAX_LOCATION_ATTEMPTS = 3;

/** Match one accessibility-tree searchbox/textbox/combobox line, capturing
 * its accessible name and its `[ref=...]` element ref. */
const FIELD_LINE_RE = /-\s*(?:searchbox|textbox|combobox)\s+"([^"]*)"[^\n[]*\[ref=([^\]]+)]/i;

/** Words (English and German) an accessible field name uses to label
 * itself a LOCATION field rather than a plain keyword/search box. */
const LOCATION_LABEL_RE = /\b(?:where|location|wo|city|region|ort|standort|stadt|plz|postleitzahl)\b/i;

/** Regexes matching a board's own statement that it did not recognise a
 * location value typed into its location control — distinct from a
 * genuine zero-result search, which the board otherwise treats as valid. */
const LOCATION_REJECTED_PATTERNS: readonly RegExp[] = [
  /\blocation not found\b/i,
  /\bno such location\b/i,
  /\binvalid location\b/i,
  /\blocation not recogni[sz]ed\b/i,
  /\bplease enter a valid location\b/i,
  /\bcould not find that location\b/i,
  /\bunknown location\b/i,
  /\bdid you mean\b/i,
  /\bmeinten sie\b/i,
  /\bort nicht gefunden\b/i,
  /\bunbekannter ort\b/i,
];

/** Local-language alias pairs for a location name — each pair tried in
 * either direction, so a board that only recognises its own country's
 * language for a location still gets a fair retry. Deliberately small: only
 * pairs actually likely to appear across the direct-search boards this tool
 * targets, not a general-purpose translation table. */
const LOCATION_ALIAS_PAIRS: ReadonlyArray<readonly [string, string]> = [
  ['Germany', 'Deutschland'],
  ['Austria', 'Österreich'],
  ['Switzerland', 'Schweiz'],
  ['Spain', 'España'],
  ['Italy', 'Italia'],
  ['Sweden', 'Sverige'],
  ['Poland', 'Polska'],
  ['Netherlands', 'Nederland'],
  ['Netherlands', 'Niederlande'],
  ['Munich', 'München'],
  ['Munich', 'Muenchen'],
  ['Cologne', 'Köln'],
  ['Nuremberg', 'Nürnberg'],
  ['Dusseldorf', 'Düsseldorf'],
  ['Hanover', 'Hannover'],
  ['Frankfurt', 'Frankfurt am Main'],
];

/** Whether `line` is one accessibility-tree field line naming itself a
 * location field — used by harvestNavigate.ts's own keyword-box detection
 * to skip a location field it must never mistake for the keyword box. */
export function isLocationFieldLine(line: string): boolean {
  const match = FIELD_LINE_RE.exec(line);
  return match !== null && LOCATION_LABEL_RE.test(match[1]);
}

/** The `[ref=...]` of the first accessibility-tree field in `snapshot` whose
 * accessible name labels it a location field, or `undefined` if none does. */
export function findLocationFieldRef(snapshot: string): string | undefined {
  for (const line of snapshot.split('\n')) {
    const match = FIELD_LINE_RE.exec(line);
    if (match && LOCATION_LABEL_RE.test(match[1])) return match[2];
  }
  return undefined;
}

/** The other-language alias(es) for `location`, matched case-insensitively
 * against either side of {@link LOCATION_ALIAS_PAIRS}. */
function aliasesFor(location: string): string[] {
  const lower = location.toLowerCase();
  const found: string[] = [];
  for (const [a, b] of LOCATION_ALIAS_PAIRS) {
    if (a.toLowerCase() === lower) found.push(b);
    else if (b.toLowerCase() === lower) found.push(a);
  }
  return found;
}

/**
 * Every location value worth trying for `location`, starting with the
 * value itself, followed by its known local-language aliases, de-duplicated
 * case-insensitively and capped at {@link MAX_LOCATION_ATTEMPTS}.
 */
export function locationCandidates(location: string): string[] {
  const candidates = [location, ...aliasesFor(location)];
  const seen = new Set<string>();
  const result: string[] = [];
  for (const candidate of candidates) {
    const key = candidate.toLowerCase();
    if (seen.has(key)) continue;
    seen.add(key);
    result.push(candidate);
    if (result.length >= MAX_LOCATION_ATTEMPTS) break;
  }
  return result;
}

/** Whether `snapshot` shows the board's own statement that a location value
 * it was just given was not recognised — as opposed to a genuine zero-result
 * search, which the board otherwise treats as a valid, understood query. */
export function showsLocationRejected(snapshot: string): boolean {
  return LOCATION_REJECTED_PATTERNS.some((re) => re.test(snapshot));
}
