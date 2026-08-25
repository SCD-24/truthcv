import Box from "@mui/material/Box";
import Button from "@mui/material/Button";
import Typography from "@mui/material/Typography";
import { useLocation, useNavigate } from "react-router-dom";
import { DocumentEditor } from "../steps/DocumentEditor";
import type { EditRequest } from "../App";
import { ROUTES } from "../routes";

/**
 * Route-level home for re-editing an already-generated document opened from
 * the ledger. Reads the `EditRequest` the ledger passed via navigation state
 * and locks the editor's save target to that application so a re-save can
 * only update the same record.
 */
export function DocumentEditPage() {
  const navigate = useNavigate();
  const location = useLocation();
  const editRequest =
    (location.state as { editRequest?: EditRequest } | null)?.editRequest ?? null;

  if (!editRequest) {
    return (
      <Box sx={{ display: "flex", flexDirection: "column", gap: 2 }}>
        <Typography variant="body1" sx={{ color: "text.secondary" }}>
          No document was chosen to edit.
        </Typography>
        <Button variant="outlined" onClick={() => navigate(ROUTES.applications)} sx={{ alignSelf: "flex-start" }}>
          Back to Applications
        </Button>
      </Box>
    );
  }

  return (
    <Box sx={{ display: "flex", flexDirection: "column", gap: 2 }}>
      <Button variant="outlined" onClick={() => navigate(ROUTES.applications)} sx={{ alignSelf: "flex-start" }}>
        Back to Applications
      </Button>
      <DocumentEditor
        kind={editRequest.kind}
        initial={editRequest.source}
        lockedAppId={editRequest.appId}
      />
    </Box>
  );
}
