import { useState } from "react";
import { deleteScreening, setScreeningRole } from "../api/client";
import type { ScreeningLedgerItem } from "../api/types";

/** Save a corrected role and replace the record with the server's
 * (normalized) response — errors propagate for RoleCell to show inline. */
export function useSaveRole(patchItem: (updated: ScreeningLedgerItem) => void) {
  const [savingRoleId, setSavingRoleId] = useState<string | null>(null);

  async function handleSaveRole(id: string, role: string) {
    setSavingRoleId(id);
    try {
      patchItem(await setScreeningRole(id, role));
    } finally {
      setSavingRoleId(null);
    }
  }

  return { savingRoleId, handleSaveRole };
}

/** Delete a screening record and refetch the current page; a failure is
 * kept as `actionError` for the page to show. */
export function useDeleteRecord(refetch: () => void) {
  const [actionError, setActionError] = useState<string | null>(null);
  const [deletingId, setDeletingId] = useState<string | null>(null);

  async function handleDelete(id: string) {
    setDeletingId(id);
    setActionError(null);
    try {
      await deleteScreening(id);
      refetch();
    } catch (e) {
      setActionError(e instanceof Error ? e.message : "Couldn't delete the screening record.");
    } finally {
      setDeletingId(null);
    }
  }

  return { actionError, deletingId, handleDelete };
}
