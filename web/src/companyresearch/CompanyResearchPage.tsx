import { useEffect, useState } from "react";
import Box from "@mui/material/Box";
import Stack from "@mui/material/Stack";
import Button from "@mui/material/Button";
import AddIcon from "@mui/icons-material/Add";
import Alert from "@mui/material/Alert";
import Typography from "@mui/material/Typography";
import CircularProgress from "@mui/material/CircularProgress";
import TextField from "@mui/material/TextField";
import ToggleButton from "@mui/material/ToggleButton";
import TablePagination from "@mui/material/TablePagination";
import {
  createCompanyFinding,
  listCompanyGroupsPage,
  listContradictions,
  resolveCompanyFinding,
} from "../api/client";
import type { CompanyFinding, CompanyGroupPage } from "../api/types";
import { CompanyCard } from "./CompanyCard";
import { FindingDialog } from "./FindingDialog";
import type { FindingDraft } from "./FindingDialog";
import { openContradictionKeys } from "./companyresearch.logic";

/** Which finding the dialog is open for: none (closed), a new one, or a
 * correction of an existing one. */
type DialogState = null | { finding?: CompanyFinding };

/** Companies per server page, matching the other paged lists' fixed size. */
const COMPANY_PAGE_SIZE = 50;

/** How long the search box waits after the last keystroke before it queries. */
const SEARCH_DEBOUNCE_MS = 300;

const LOAD_ERROR = "Couldn't load company research.";

function errorMessage(e: unknown, fallback: string): string {
  return e instanceof Error ? e.message : fallback;
}

/** Which server page is shown: the page index plus the filters it was asked with. */
type ResearchPos = { page: number; q: string; needsReview: boolean };

/** One loaded page plus the open contradictions its cards mark per claim. */
type ResearchData = { groups: CompanyGroupPage; contested: Set<string> };

/** Fetch the page `pos` names, again whenever `nonce` changes. Each fetch
 * supersedes the one before it, so a stale response never overwrites a newer
 * one; an empty page beyond the first steps back a page. */
function useResearchFetch(pos: ResearchPos, nonce: number, setPos: (p: ResearchPos) => void) {
  const [data, setData] = useState<ResearchData | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let live = true;
    const { page, q, needsReview } = pos;
    const offset = page * COMPANY_PAGE_SIZE;
    const groupsPage = listCompanyGroupsPage({ limit: COMPANY_PAGE_SIZE, offset, q, needsReview });
    Promise.all([groupsPage, listContradictions()])
      .then(([groups, contradictions]) => {
        if (!live) return;
        setError(null);
        setData({ groups, contested: openContradictionKeys(contradictions) });
        if (groups.items.length === 0 && page > 0) setPos({ ...pos, page: page - 1 });
      })
      .catch((e) => live && setError(errorMessage(e, LOAD_ERROR)));
    return () => {
      live = false;
    };
  }, [pos, nonce, setPos]);

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
 * (debounced) and needs-review filters (both reset to page 1), and a refetch. */
function useResearchPage() {
  const [pos, setPos] = useState<ResearchPos>({ page: 0, q: "", needsReview: false });
  const [nonce, setNonce] = useState(0);
  const [query, setQuery] = useState("");
  const { clearError, ...fetched } = useResearchFetch(pos, nonce, setPos);
  useDebouncedSearch(query, setPos);
  const refetch = () => setNonce((n) => n + 1);

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
      refetch();
    },
  };
}

type ResearchView = ReturnType<typeof useResearchPage>;

/** Search box, needs-review toggle and the add button above the list. */
function ResearchToolbar({ view, onAdd }: { view: ResearchView; onAdd: () => void }) {
  return (
    <Stack
      direction="row"
      spacing={2}
      sx={{ mb: 3, alignItems: "center", flexWrap: "wrap", rowGap: 1 }}
    >
      <TextField
        size="small"
        type="search"
        label="Search companies"
        value={view.query}
        onChange={(e) => view.setQuery(e.target.value)}
        sx={{ flex: 1, minWidth: 220 }}
      />
      <ToggleButton
        value="needs-review"
        size="small"
        selected={view.needsReview}
        aria-pressed={view.needsReview}
        onChange={view.toggleNeedsReview}
      >
        Needs review
      </ToggleButton>
      <Button variant="contained" startIcon={<AddIcon />} onClick={onAdd}>
        Add finding
      </Button>
    </Stack>
  );
}

type CardActions = {
  busy: boolean;
  onResolve: (id: string, resolution: "accepted" | "rejected") => void;
  onCorrect: (finding: CompanyFinding) => void;
};

/** One loaded page of company cards and the page controls under it. */
function CompanyList({ view, data, actions }: {
  view: ResearchView;
  data: ResearchData;
  actions: CardActions;
}) {
  return (
    <Stack spacing={2}>
      {data.groups.items.map((group) => (
        <CompanyCard key={group.companyKey} group={group} contested={data.contested} {...actions} />
      ))}
      <TablePagination
        component="div"
        count={data.groups.total}
        page={view.page}
        rowsPerPage={COMPANY_PAGE_SIZE}
        rowsPerPageOptions={[COMPANY_PAGE_SIZE]}
        onPageChange={(_, p) => view.setPage(p)}
      />
    </Stack>
  );
}

/** Loading, empty, no-match, or the loaded list; nothing while a load error shows. */
function ResearchBody({ view, actions, onAdd }: {
  view: ResearchView;
  actions: CardActions;
  onAdd: () => void;
}) {
  const { data, error } = view;
  if (error) return null;
  if (!data) {
    return (
      <Stack direction="row" spacing={2} sx={{ py: 6, justifyContent: "center" }}>
        <CircularProgress size={20} sx={{ color: "var(--attest)" }} />
        <Typography color="text.secondary">Loading company research…</Typography>
      </Stack>
    );
  }
  if (data.groups.companies.length === 0) {
    return (
      <Stack spacing={2} sx={{ py: 6, alignItems: "center" }}>
        <Typography color="text.secondary">No company findings recorded yet.</Typography>
        <Button variant="outlined" onClick={onAdd}>
          Add the first finding
        </Button>
      </Stack>
    );
  }
  if (data.groups.total === 0) {
    return (
      <Typography color="text.secondary" sx={{ py: 6, textAlign: "center" }}>
        No companies match your search or filter.
      </Typography>
    );
  }
  return <CompanyList view={view} data={data} actions={actions} />;
}

/**
 * The Company Research page — a searchable list with one card per company,
 * each showing the current sourced, dated value per claim. Sources that
 * disagree on a claim surface as an open contradiction the operator resolves
 * by accepting or rejecting a finding. Findings are immutable: adding and
 * correcting both record a new finding in a dialog; a correction supersedes
 * the old one.
 */
export function CompanyResearchPage() {
  const view = useResearchPage();
  const [actionError, setActionError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [dialog, setDialog] = useState<DialogState>(null);

  /** Accept or reject a finding, then refetch so the contradiction clears. */
  async function handleResolve(id: string, resolution: "accepted" | "rejected") {
    setBusy(true);
    setActionError(null);
    try {
      await resolveCompanyFinding(id, resolution);
      view.refetch();
    } catch (e) {
      setActionError(errorMessage(e, "Couldn't record your decision."));
    } finally {
      setBusy(false);
    }
  }

  /** Record a finding (new or superseding) and refetch. A create error
   * propagates to the dialog; a refetch error is a load error. */
  async function handleSubmit(draft: FindingDraft) {
    await createCompanyFinding(draft);
    view.refetch();
  }

  const openAdd = () => setDialog({});
  const actions: CardActions = {
    busy,
    onResolve: handleResolve,
    onCorrect: (finding) => setDialog({ finding }),
  };

  return (
    <Box className="company-research-page" aria-labelledby="company-research-title">
      <Stack
        direction="row"
        sx={{ mb: 3, alignItems: "flex-start", justifyContent: "space-between", gap: 2 }}
      >
        <Box>
          <Typography
            variant="overline"
            className="company-research__eyebrow"
            sx={{ display: "block" }}
          >
            Sourced &amp; dated
          </Typography>
          <Typography id="company-research-title" variant="h4" component="h1">
            Company Research
          </Typography>
        </Box>
      </Stack>

      <ResearchToolbar view={view} onAdd={openAdd} />

      {view.error && (
        <Alert
          severity="error"
          sx={{ mb: 2 }}
          action={
            <Button color="inherit" size="small" onClick={view.retry}>
              Retry
            </Button>
          }
        >
          {view.error}
        </Alert>
      )}
      {actionError && (
        <Alert severity="error" sx={{ mb: 2 }} onClose={() => setActionError(null)}>
          {actionError}
        </Alert>
      )}

      <ResearchBody view={view} actions={actions} onAdd={openAdd} />

      {dialog ? (
        <FindingDialog
          key={dialog.finding?.id ?? "new"}
          finding={dialog.finding}
          companies={view.data?.groups.companies ?? []}
          onClose={() => setDialog(null)}
          onSubmit={handleSubmit}
        />
      ) : null}
    </Box>
  );
}
