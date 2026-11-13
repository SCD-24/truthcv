import { useEffect, useState } from "react";
import { listScreeningLedgerPage } from "../api/client";
import type { ScreeningLedgerItem, ScreeningLedgerPage } from "../api/types";

/** Rows per ledger page, matching the other paged lists' fixed size. */
export const LEDGER_PAGE_SIZE = 50;

type LedgerPos = { page: number; blockedOnly: boolean };

/** Fetch the ledger page `pos` names, again whenever `nonce` changes. Each
 * fetch supersedes the one before it, so a stale response never overwrites a
 * newer one; a page a delete emptied moves back to the last page with rows.
 * Loading is the state before the first response or error. */
function useLedgerFetch(pos: LedgerPos, nonce: number, setPos: (p: LedgerPos) => void) {
  const [data, setData] = useState<ScreeningLedgerPage | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let live = true;
    const { page, blockedOnly } = pos;
    listScreeningLedgerPage({ limit: LEDGER_PAGE_SIZE, offset: page * LEDGER_PAGE_SIZE, blockedOnly })
      .then((res) => {
        if (!live) return;
        setError(null);
        setData(res);
        const next = Math.min(page, Math.max(0, Math.ceil(res.total / LEDGER_PAGE_SIZE) - 1));
        if (next !== page) setPos({ page: next, blockedOnly });
      })
      .catch((e) => live && setError(e instanceof Error ? e.message : "Couldn't load screenings."));
    return () => {
      live = false;
    };
  }, [pos, nonce, setPos]);

  return { data, setData, error };
}

/** The ledger's server page plus its position: the page, the blocked-only
 * filter (which resets to the first page), a refetch, and an in-place patch. */
export function useLedgerPage() {
  const [pos, setPos] = useState<LedgerPos>({ page: 0, blockedOnly: false });
  const [nonce, setNonce] = useState(0);
  const { setData, ...fetched } = useLedgerFetch(pos, nonce, setPos);

  /** Swap in an edited record without refetching. */
  const patchItem = (updated: ScreeningLedgerItem) =>
    setData((d) => d && { ...d, items: d.items.map((r) => (r.id === updated.id ? updated : r)) });

  return {
    ...pos,
    ...fetched,
    setPage: (page: number) => setPos((p) => ({ ...p, page })),
    setBlockedOnly: (blockedOnly: boolean) => setPos({ page: 0, blockedOnly }),
    refetch: () => setNonce((n) => n + 1),
    patchItem,
  };
}

export type LedgerView = ReturnType<typeof useLedgerPage>;
