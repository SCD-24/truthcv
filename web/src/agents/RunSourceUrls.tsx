import { useCallback, useEffect, useRef, useState } from "react";
import { Box, Button, Link, Typography } from "@mui/material";
import type { BoardBreakdown, RunUrlEntry } from "../api/types";
import { getRunUrls } from "../api/client";
import { ROUTES } from "../routes";
import { OUTCOME_SECTION_ORDER, type FunnelColumn } from "./runFunnel";

const PAGE_SIZE = 50;

function useUrlPage(runId: string, source: string, channel: string, outcome: FunnelColumn["outcome"], enabled: boolean) {
  const [entries, setEntries] = useState<RunUrlEntry[]>([]);
  const [total, setTotal] = useState(0);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const started = useRef(false);
  const alive = useRef(true);
  useEffect(() => {
    alive.current = true;
    return () => {
      alive.current = false;
    };
  }, []);

  const load = useCallback(
    async (offset: number) => {
      if (!outcome) return;
      setLoading(true);
      setError(null);
      try {
        const page = await getRunUrls(runId, { source, channel, outcome, limit: PAGE_SIZE, offset });
        if (!alive.current) return;
        setEntries((prev) => (offset === 0 ? page.entries : [...prev, ...page.entries]));
        setTotal(page.total);
      } catch (err) {
        if (!alive.current) return;
        setError(err instanceof Error ? err.message : String(err));
      } finally {
        if (alive.current) setLoading(false);
      }
    },
    [runId, source, channel, outcome],
  );

  useEffect(() => {
    if (enabled && !started.current) {
      started.current = true;
      void load(0);
    }
  }, [enabled, load]);

  return { entries, total, loading, error, load };
}

function destination(outcome: FunnelColumn["outcome"]): string | null {
  if (outcome === "for_review") return ROUTES.approvals;
  if (outcome === "rejected") return ROUTES.screenings;
  return null;
}

function EntryList({ entries, outcome }: { entries: RunUrlEntry[]; outcome: FunnelColumn["outcome"] }) {
  const dest = destination(outcome);
  return (
    <Box component="ul" sx={{ listStyle: "none", m: 0, p: 0 }}>
      {entries.map((e) => (
        <Box component="li" key={e.url} sx={{ py: 0.25, wordBreak: "break-all" }}>
          <Link href={e.url} target="_blank" rel="noopener noreferrer">
            {e.url}
          </Link>
          {e.detail && (
            <Typography component="span" variant="body2" color="text.secondary">
              {" "}
              — {e.detail}
            </Typography>
          )}
        </Box>
      ))}
      {dest && (
        <Box component="li" sx={{ pt: 0.5 }}>
          <Link href={dest}>{outcome === "for_review" ? "Open approvals" : "Open screenings"}</Link>
        </Box>
      )}
    </Box>
  );
}

interface SectionProps {
  runId: string;
  row: BoardBreakdown;
  column: FunnelColumn;
  count: number;
}

function OutcomeSection({ runId, row, column, count }: SectionProps) {
  const [open, setOpen] = useState(column.outcome !== "previously_screened");
  const { entries, total, loading, error, load } = useUrlPage(runId, row.board, row.channel, column.outcome, open);
  return (
    <Box sx={{ mb: 1 }}>
      <Box
        component="button"
        type="button"
        aria-expanded={open}
        onClick={() => setOpen(!open)}
        sx={{ font: "inherit", fontWeight: 600, color: "inherit", background: "none", border: 0, p: 0, cursor: "pointer", "&:focus-visible": { outline: "2px solid currentColor", outlineOffset: 2 } }}
      >
        {column.label} ({count})
      </Box>
      {open && (
        <Box>
          <EntryList entries={entries} outcome={column.outcome} />
          <Box aria-live="polite">{loading && <Typography variant="body2">Loading…</Typography>}</Box>
          {error && (
            <Box role="alert">
              <Typography variant="body2" color="error">
                Couldn't load links: {error}
              </Typography>
              <Button size="small" onClick={() => void load(entries.length)}>
                Retry
              </Button>
            </Box>
          )}
          {!loading && !error && entries.length < total && (
            <Button size="small" onClick={() => void load(entries.length)}>
              Show more
            </Button>
          )}
        </Box>
      )}
    </Box>
  );
}

/** Lazily loaded URL lists, one section per non-zero outcome of a source row. */
export function RunSourceUrls({ runId, row, truncated }: { runId: string; row: BoardBreakdown; truncated: boolean }) {
  return (
    <Box sx={{ py: 1 }}>
      {truncated && (
        <Typography variant="body2" color="text.secondary" sx={{ mb: 1 }}>
          Only the first 1,000 links of this run were kept
        </Typography>
      )}
      {OUTCOME_SECTION_ORDER.map((column) => {
        const count = row[column.key];
        return count ? <OutcomeSection key={column.key} runId={runId} row={row} column={column} count={count} /> : null;
      })}
    </Box>
  );
}
