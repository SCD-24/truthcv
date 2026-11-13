import Stack from "@mui/material/Stack";
import Button from "@mui/material/Button";
import AddIcon from "@mui/icons-material/Add";
import Typography from "@mui/material/Typography";
import CircularProgress from "@mui/material/CircularProgress";
import TextField from "@mui/material/TextField";
import ToggleButton from "@mui/material/ToggleButton";
import TablePagination from "@mui/material/TablePagination";
import type { CompanyFinding } from "../api/types";
import { CompanyCard } from "./CompanyCard";
import { COMPANY_PAGE_SIZE } from "./useResearchPage";
import type { ResearchData, ResearchView } from "./useResearchPage";

/** The search box above the list. */
function SearchBox({ view }: { view: ResearchView }) {
  return (
    <TextField
      size="small"
      type="search"
      label="Search companies"
      value={view.query}
      onChange={(e) => view.setQuery(e.target.value)}
      sx={{ flex: 1, minWidth: 220 }}
    />
  );
}

/** Search box, needs-review toggle and the add button above the list. */
export function ResearchToolbar({ view, onAdd }: { view: ResearchView; onAdd: () => void }) {
  return (
    <Stack
      direction="row"
      spacing={2}
      sx={{ mb: 3, alignItems: "center", flexWrap: "wrap", rowGap: 1 }}
    >
      <SearchBox view={view} />
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

export type CardActions = {
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

function LoadingState() {
  return (
    <Stack direction="row" spacing={2} sx={{ py: 6, justifyContent: "center" }}>
      <CircularProgress size={20} sx={{ color: "var(--attest)" }} />
      <Typography color="text.secondary">Loading company research…</Typography>
    </Stack>
  );
}

function EmptyState({ onAdd }: { onAdd: () => void }) {
  return (
    <Stack spacing={2} sx={{ py: 6, alignItems: "center" }}>
      <Typography color="text.secondary">No company findings recorded yet.</Typography>
      <Button variant="outlined" onClick={onAdd}>
        Add the first finding
      </Button>
    </Stack>
  );
}

/** Loading, empty, no-match, or the loaded list; nothing while a load error shows. */
export function ResearchBody({ view, actions, onAdd }: {
  view: ResearchView;
  actions: CardActions;
  onAdd: () => void;
}) {
  const { data, error } = view;
  if (error) return null;
  if (!data) return <LoadingState />;
  if (data.groups.companies.length === 0) return <EmptyState onAdd={onAdd} />;
  if (data.groups.total === 0) {
    return (
      <Typography color="text.secondary" sx={{ py: 6, textAlign: "center" }}>
        No companies match your search or filter.
      </Typography>
    );
  }
  return <CompanyList view={view} data={data} actions={actions} />;
}
