/** Approximates the server's collision key for a board source
 * (`source.strip().casefold()` in Python). JS has no casefold, but
 * normalizing then upper-casing then lower-casing gets close enough for the
 * cases that matter here: toUpperCase maps ß to SS, so "straße.de" and
 * "strasse.de" land on the same key, matching Python's casefold. */
export function sourceKey(source: string): string {
  return source.trim().normalize("NFKC").toUpperCase().toLowerCase();
}
