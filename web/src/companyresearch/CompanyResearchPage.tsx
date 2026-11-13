import Box from "@mui/material/Box";
import Stack from "@mui/material/Stack";
import Button from "@mui/material/Button";
import Alert from "@mui/material/Alert";
import Typography from "@mui/material/Typography";
import { FindingDialog } from "./FindingDialog";
import { ResearchBody, ResearchToolbar } from "./ResearchList";
import { useResearchActions } from "./useResearchActions";
import { useResearchPage } from "./useResearchPage";
import type { ResearchView } from "./useResearchPage";

function ResearchHeader() {
  return (
    <Stack
      direction="row"
      sx={{ mb: 3, alignItems: "flex-start", justifyContent: "space-between", gap: 2 }}
    >
      <Box>
        <Typography variant="overline" className="company-research__eyebrow" sx={{ display: "block" }}>
          Sourced &amp; dated
        </Typography>
        <Typography id="company-research-title" variant="h4" component="h1">
          Company Research
        </Typography>
      </Box>
    </Stack>
  );
}

/** The load error (with Retry) and the dismissable action error. */
function ResearchAlerts({ view, actionError, onDismiss }: {
  view: ResearchView;
  actionError: string | null;
  onDismiss: () => void;
}) {
  const retry = (
    <Button color="inherit" size="small" onClick={view.retry}>
      Retry
    </Button>
  );
  return (
    <>
      {view.error && <Alert severity="error" sx={{ mb: 2 }} action={retry}>{view.error}</Alert>}
      {actionError && (
        <Alert severity="error" sx={{ mb: 2 }} onClose={onDismiss}>
          {actionError}
        </Alert>
      )}
    </>
  );
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
  const { actions, actionError, setActionError, dialog, setDialog, handleSubmit } = useResearchActions(view);
  const openAdd = () => setDialog({});
  return (
    <Box className="company-research-page" aria-labelledby="company-research-title">
      <ResearchHeader />
      <ResearchToolbar view={view} onAdd={openAdd} />
      <ResearchAlerts view={view} actionError={actionError} onDismiss={() => setActionError(null)} />
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
