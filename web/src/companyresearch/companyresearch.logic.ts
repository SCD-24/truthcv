import { CLAIM_TYPES } from "../api/types";
import type { CompanyFinding, ContradictionGroup } from "../api/types";

/** Source classes, strongest evidence first. The select is populated from this
 * list in order, and the ranking below is just its index. */
export const SOURCE_CLASSES = [
  "audited_accounts",
  "regulatory_filing",
  "listed_bond_price",
  "company_statement",
  "press",
  "review_site",
  "unattributed",
] as const;

/** Strength rank of a source class: lower is stronger. An unknown class is
 * ranked below every known one, so it always sorts last. */
export function sourceRank(sourceClass: string): number {
  const i = (SOURCE_CLASSES as readonly string[]).indexOf(sourceClass);
  return i === -1 ? SOURCE_CLASSES.length : i;
}

/** Human wording for a source class — underscores are just storage. */
export function sourceClassLabel(sourceClass: string): string {
  return sourceClass ? sourceClass.replace(/_/g, " ") : "unattributed";
}

/** The as-of date to show for a finding. Empty means the source date is
 * unknown — render the literal "unknown", never blank and never observedAt. */
export function formatAsOf(finding: CompanyFinding): string {
  return finding.asOf.trim() ? finding.asOf : "unknown";
}

/** The row key of a finding's claim: the claim itself, except 'other' rows are
 * distinguished by their trimmed, casefolded label. */
export function claimKey(finding: CompanyFinding): string {
  return finding.claim === "other"
    ? "other:" + (finding.claimLabel ?? "").trim().toLowerCase()
    : finding.claim;
}

/** Row label: the claim type's display label, or claimLabel for 'other'. An
 * unknown (legacy free-text) claim renders raw. */
export function claimRowLabel(finding: CompanyFinding): string {
  if (finding.claim === "other") return finding.claimLabel?.trim() || "Other";
  const known = CLAIM_TYPES.find((t) => t.value === finding.claim);
  return known ? known.label : finding.claimLabel?.trim() || finding.claim;
}

/** One company (all spellings sharing a companyKey) and its findings. */
export interface CompanyGroup {
  companyKey: string;
  company: string;
  findings: CompanyFinding[];
}

function identity(finding: CompanyFinding): string {
  return finding.companyKey || finding.company;
}

/** Group findings by companyKey; the display name is the most recently
 * observed spelling. Sorted alphabetically by display name. Pure. */
export function groupFindingsByCompany(findings: CompanyFinding[]): CompanyGroup[] {
  const map = new Map<string, CompanyFinding[]>();
  for (const finding of findings) {
    const list = map.get(identity(finding));
    if (list) list.push(finding);
    else map.set(identity(finding), [finding]);
  }
  const groups = Array.from(map, ([companyKey, grouped]) => {
    let newest = grouped[0];
    for (const f of grouped) if (f.observedAt > newest.observedAt) newest = f;
    return { companyKey, company: newest.company, findings: grouped };
  });
  return groups.sort((a, b) =>
    a.company.localeCompare(b.company, undefined, { sensitivity: "base" }),
  );
}

/** One claim row and the findings that cite a value for it. */
export interface ClaimGroup {
  claimKey: string;
  label: string;
  findings: CompanyFinding[];
}

/** Group findings by claimKey, preserving first-seen order. Pure. */
export function groupByClaim(findings: CompanyFinding[]): ClaimGroup[] {
  const map = new Map<string, ClaimGroup>();
  for (const finding of findings) {
    const key = claimKey(finding);
    const group = map.get(key);
    if (group) group.findings.push(finding);
    else map.set(key, { claimKey: key, label: claimRowLabel(finding), findings: [finding] });
  }
  return Array.from(map.values());
}

/** Findings sorted strongest source first; does not mutate its argument. */
export function bySourceRank(findings: CompanyFinding[]): CompanyFinding[] {
  return [...findings].sort((a, b) => sourceRank(a.sourceClass) - sourceRank(b.sourceClass));
}

/** The key identifying a (company, claim row) pair. */
export function contradictionKey(companyKey: string, claimRowKey: string): string {
  return `${companyKey}\u0000${claimRowKey}`;
}

/** Every (companyKey, claimKey) the backend reports as an open contradiction. */
export function openContradictionKeys(groups: ContradictionGroup[]): Set<string> {
  const keys = new Set<string>();
  for (const group of groups) {
    for (const finding of group.findings) {
      keys.add(contradictionKey(identity(finding), claimKey(finding)));
    }
  }
  return keys;
}

/** Ids of findings that some other finding corrects. */
export function supersededIds(findings: CompanyFinding[]): Set<string> {
  const ids = new Set<string>();
  for (const f of findings) if (f.supersedes) ids.add(f.supersedes);
  return ids;
}

function isLive(finding: CompanyFinding, superseded: Set<string>): boolean {
  return !superseded.has(finding.id) && finding.resolution !== "rejected";
}

/** Per claimKey, the newest-observed finding that is neither superseded nor
 * rejected. Pass one company's findings. Pure. */
export function currentByClaim(findings: CompanyFinding[]): Map<string, CompanyFinding> {
  const superseded = supersededIds(findings);
  const out = new Map<string, CompanyFinding>();
  for (const f of findings) {
    if (!isLive(f, superseded)) continue;
    const key = claimKey(f);
    const cur = out.get(key);
    if (!cur || f.observedAt > cur.observedAt) out.set(key, f);
  }
  return out;
}

/** Findings of one claim row that are superseded or rejected, newest first.
 * Omit claimRowKey for every row of the given findings. */
export function historyFor(findings: CompanyFinding[], claimRowKey?: string): CompanyFinding[] {
  const superseded = supersededIds(findings);
  return findings
    .filter((f) => (claimRowKey === undefined || claimKey(f) === claimRowKey))
    .filter((f) => !isLive(f, superseded))
    .sort((a, b) => (a.observedAt < b.observedAt ? 1 : a.observedAt > b.observedAt ? -1 : 0));
}

/** Live findings of one claim row — the contenders when it is contested. */
export function liveFindings(findings: CompanyFinding[], claimRowKey: string): CompanyFinding[] {
  const superseded = supersededIds(findings);
  return findings.filter((f) => claimKey(f) === claimRowKey && isLive(f, superseded));
}

/** Companies whose name or any finding value contains the query
 * (case-insensitive). An empty query keeps everything. */
export function filterCompanies(groups: CompanyGroup[], query: string): CompanyGroup[] {
  const q = query.trim().toLowerCase();
  if (!q) return groups;
  return groups.filter(
    (g) =>
      g.company.toLowerCase().includes(q) ||
      g.findings.some((f) => f.value.toLowerCase().includes(q)),
  );
}

/** Distinct display names, for the company autocomplete. */
export function knownCompanies(groups: CompanyGroup[]): string[] {
  return groups.map((g) => g.company);
}
