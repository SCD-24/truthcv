import { useEffect, useRef, useState } from "react";
import { listCompanyGroupsPage, listContradictions } from "../api/client";
import type { CompanyGroupPage } from "../api/types";
import { openContradictionKeys } from "./companyresearch.logic";

/** Companies per server page, matching the other paged lists' fixed size. */
export const COMPANY_PAGE_SIZE = 50;

/** How long the search box waits after the last keystroke before it queries. */
const SEARCH_DEBOUNCE_MS = 300;

const LOAD_ERROR = "Couldn't load company research.";

export function errorMessage(e: unknown, fallback: string): string {
  return e instanceof Error ? e.message : fallback;
}

/** Which server page is shown: the page index plus the filters it was asked with. */
type ResearchPos = { page: number; q: string; needsReview: boolean };

/** One loaded page plus the open contradictions its cards mark per claim. */
export type ResearchData = { groups: CompanyGroupPage; contested: Set<string> };

/** Fetch the page `pos` names together with the open contradictions. */
async function fetchResearch({ page, q, needsReview }: ResearchPos): Promise<ResearchData> {
  const offset = page * COMPANY_PAGE_SIZE;
  const groupsPage = listCompanyGroupsPage({ limit: COMPANY_PAGE_SIZE, offset, q, needsReview });
  const [groups, contradictions] = await Promise.all([groupsPage, listContradictions()]);
  return { groups, contested: openContradictionKeys(contradictions) };
}

/** A refetch trigger: bumping `nonce` refetches, and the returned promise
 * resolves when `settled`'s waiters are called after that fetch settles. */
function useRefetch() {
  const [nonce, setNonce] = useState(0);
  const settled = useRef<Array<() => void>>([]);
  const refetch = () => {
    const done = new Promise<void>((resolve) => settled.current.push(resolve));
    setNonce((n) => n + 1);
    return done;
  };
  return { nonce, settled, refetch };
}

type Refetcher = ReturnType<typeof useRefetch>;
type SetPos = (p: ResearchPos) => void;

/** Fetch the page `pos` names, again whenever `nonce` changes. Each fetch
 * supersedes the one before it, so a stale response never overwrites a newer
 * one; an empty page beyond the first steps back a page. Once the current
 * fetch settles (either way), every waiter registered in `settled` is called. */
function useResearchFetch(pos: ResearchPos, { nonce, settled }: Refetcher, setPos: SetPos) {
  const [data, setData] = useState<ResearchData | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let live = true;
    fetchResearch(pos)
      .then((loaded) => {
        if (!live) return;
        setError(null);
        setData(loaded);
        if (loaded.groups.items.length === 0 && pos.page > 0) setPos({ ...pos, page: pos.page - 1 });
      })
      .catch((e) => live && setError(errorMessage(e, LOAD_ERROR)))
      .finally(() => live && settled.current.splice(0).forEach((done) => done()));
    return () => {
      live = false;
    };
  }, [pos, nonce, settled, setPos]);

  return { data, error, clearError: () => setError(null) };
}

/** Send the typed search once typing pauses; a changed query resets to page 1. */
function useDebouncedSearch(
  query: string,
  setPos: (update: (p: ResearchPos) => ResearchPos) => void,
) {
  useEffect(() => {
    const timer = setTimeout(
      () => setPos((p) => (p.q === query ? p : { ...p, page: 0, q: query })),
      SEARCH_DEBOUNCE_MS,
    );
    return () => clearTimeout(timer);
  }, [query, setPos]);
}

/** The research list's server page plus its position: the page, the search
 * (debounced) and needs-review filters (both reset to page 1), and a refetch
 * whose promise resolves once that refetch has settled, success or failure. */
export function useResearchPage() {
  const [pos, setPos] = useState<ResearchPos>({ page: 0, q: "", needsReview: false });
  const [query, setQuery] = useState("");
  const refetcher = useRefetch();
  const { clearError, ...fetched } = useResearchFetch(pos, refetcher, setPos);
  useDebouncedSearch(query, setPos);
  const { refetch } = refetcher;

  return {
    ...pos,
    ...fetched,
    query,
    setQuery,
    setPage: (page: number) => setPos((p) => ({ ...p, page })),
    toggleNeedsReview: () => setPos((p) => ({ ...p, page: 0, needsReview: !p.needsReview })),
    refetch,
    retry: () => {
      clearError();
      void refetch();
    },
  };
}

export type ResearchView = ReturnType<typeof useResearchPage>;
