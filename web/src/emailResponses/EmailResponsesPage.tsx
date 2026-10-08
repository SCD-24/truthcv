import { useEffect, useRef, useState } from "react";
import Alert from "@mui/material/Alert";
import Box from "@mui/material/Box";
import CircularProgress from "@mui/material/CircularProgress";
import Link from "@mui/material/Link";
import Typography from "@mui/material/Typography";
import {
  acceptGmailSuggestion,
  dismissGmailSuggestions,
  getGmailStatus,
  getJevSettings,
  listGmailSuggestions,
} from "../api/client";
import type { GmailSuggestion } from "../api/types";
import { EmailResponsesList, PAGE_SIZE } from "./EmailResponsesList";

function errText(e: unknown, fallback: string): string {
  return e instanceof Error ? e.message : fallback;
}

/** Page to step back to when the current page would be past the last row. */
function targetPage(page: number, pending: number): number {
  if (page > 0 && page * PAGE_SIZE >= pending) {
    return Math.max(0, Math.ceil(pending / PAGE_SIZE) - 1);
  }
  return page;
}

function companyOf(label: string): string {
  const i = label.lastIndexOf(" — ");
  return i > 0 ? label.slice(0, i) : label;
}

function TrackingOff({ onOpenSettings }: { onOpenSettings?: () => void }) {
  return (
    <Box>
      <Typography variant="h2" sx={{ fontSize: "1.25rem" }}>
        Email response tracking is off
      </Typography>
      <Typography color="text.secondary">
        Turn on Gmail response tracking to review replies here.{" "}
        <Link component="button" type="button" onClick={onOpenSettings}>
          Open Settings
        </Link>
      </Typography>
    </Box>
  );
}

/** Email responses review page: replies Gmail sync couldn't apply on its own. */
export function EmailResponsesPage({ onOpenSettings }: { onOpenSettings?: () => void }) {
  const [trackingOn, setTrackingOn] = useState<boolean | null>(null);
  const [loading, setLoading] = useState(true);
  const [items, setItems] = useState<GmailSuggestion[]>([]);
  const [total, setTotal] = useState(0);
  const [page, setPage] = useState(0);
  const [pendingIds, setPendingIds] = useState<string[]>([]);
  const [announcement, setAnnouncement] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [loaded, setLoaded] = useState(false);
  const pageRef = useRef(0);
  const loadSeq = useRef(0);
  const mounted = useRef(true);

  useEffect(() => {
    mounted.current = true;
    return () => {
      mounted.current = false;
    };
  }, []);

  async function loadPage(p: number) {
    const seq = ++loadSeq.current;
    try {
      const res = await listGmailSuggestions(PAGE_SIZE, p * PAGE_SIZE);
      if (!mounted.current || seq !== loadSeq.current) return;
      setItems(res.items);
      setTotal(res.total);
      setPage(p);
      pageRef.current = p;
      setLoaded(true);
    } catch (e) {
      if (!mounted.current || seq !== loadSeq.current) return;
      setError(errText(e, "Couldn't load email responses."));
    }
  }

  useEffect(() => {
    Promise.all([getJevSettings(), getGmailStatus()])
      .then(async ([j, g]) => {
        const on = g.connected && j.keySet && j.useForEmailTracking;
        if (!mounted.current) return;
        setTrackingOn(on);
        if (on) await loadPage(0);
      })
      .catch((e: unknown) => {
        if (mounted.current) setError(errText(e, "Couldn't load Gmail settings."));
      })
      .finally(() => {
        if (mounted.current) setLoading(false);
      });
  }, []);

  async function runAction(ids: string[], act: () => Promise<number>, fallback: string) {
    setPendingIds(ids);
    setError(null);
    try {
      const pending = await act();
      await loadPage(targetPage(pageRef.current, pending));
    } catch (e) {
      if (mounted.current) setError(errText(e, fallback));
      await loadPage(pageRef.current);
    } finally {
      if (mounted.current) setPendingIds([]);
    }
  }

  function handleDismiss(ids: string[]) {
    return runAction(
      ids,
      async () => {
        const res = await dismissGmailSuggestions(ids);
        setAnnouncement(
          `Dismissed ${res.dismissed} email response${res.dismissed === 1 ? "" : "s"}`,
        );
        return res.pending;
      },
      "Couldn't dismiss email responses.",
    );
  }

  function handleAccept(item: GmailSuggestion) {
    return runAction(
      [item.id],
      async () => {
        const res = await acceptGmailSuggestion(item.id);
        setAnnouncement(
          `Marked ${companyOf(item.application_label)} as ${item.suggested_status}`,
        );
        return res.pending;
      },
      "Couldn't update the application.",
    );
  }

  return (
    <section>
      <div className="stage__head">
        <h1 className="stage__title">Email responses</h1>
        <p className="stage__lede">
          Replies to your applications that Gmail sync couldn't match with enough
          confidence to apply on its own. Accept the ones that are right, dismiss the rest.
        </p>
      </div>
      {error && (
        <Alert severity="error" sx={{ mb: 3 }}>
          {error}
        </Alert>
      )}
      <div aria-live="polite" role="status">
        {announcement}
      </div>
      {loading ? (
        <Box role="status" aria-live="polite" sx={{ display: "flex", gap: 2, alignItems: "center" }}>
          <CircularProgress size={20} />
          <Typography sx={{ color: "text.secondary" }}>Loading email responses…</Typography>
        </Box>
      ) : trackingOn === false ? (
        <TrackingOff onOpenSettings={onOpenSettings} />
      ) : trackingOn && !loaded ? null : trackingOn && items.length === 0 && total === 0 ? (
        <Typography color="text.secondary">No email responses to review.</Typography>
      ) : trackingOn ? (
        <EmailResponsesList
          items={items}
          total={total}
          page={page}
          pendingIds={pendingIds}
          bulkBusy={pendingIds.length > 0}
          onPageChange={(p) => void loadPage(p)}
          onDismiss={(ids) => void handleDismiss(ids)}
          onAccept={(item) => void handleAccept(item)}
        />
      ) : null}
    </section>
  );
}
