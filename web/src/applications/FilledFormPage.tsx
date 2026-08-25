import { useEffect, useState } from "react";
import { useParams } from "react-router-dom";
import Box from "@mui/material/Box";
import Stack from "@mui/material/Stack";
import Button from "@mui/material/Button";
import ArrowBackIcon from "@mui/icons-material/ArrowBack";
import Typography from "@mui/material/Typography";
import Table from "@mui/material/Table";
import TableHead from "@mui/material/TableHead";
import TableBody from "@mui/material/TableBody";
import TableRow from "@mui/material/TableRow";
import TableCell from "@mui/material/TableCell";
import TableContainer from "@mui/material/TableContainer";
import { listApplications } from "../api/client";
import type { Application } from "../api/types";
import "../styles/applications.css";

/**
 * Read-only view of the evidence the agent recorded while filling out and
 * submitting one application's form: the field values it actually typed, its
 * confirmation that the submission went through, the pre-application
 * screening verdict, and any files it attached. There is no PATCH here — this
 * is a record of what happened, not something the user edits.
 *
 * There is no GET /api/applications/{id} route, so this loads the full ledger
 * via listApplications() and selects the matching id client-side.
 */
export function FilledFormPage({ onBack }: { onBack: () => void }) {
  const { id } = useParams<{ id: string }>();
  const [apps, setApps] = useState<Application[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    listApplications()
      .then(setApps)
      .catch((e) => setError(e instanceof Error ? e.message : "Couldn't load applications."));
  }, []);

  const header = (
    <Stack
      direction="row"
      className="apps-page__head"
      sx={{ mb: 3, alignItems: "flex-start", justifyContent: "space-between", gap: 2 }}
    >
      <Box>
        <Typography variant="overline" className="apps__eyebrow" sx={{ display: "block" }}>
          Outbound record
        </Typography>
        <Typography id="apps-title" variant="h4" component="h1" className="apps-page__title">
          Filled form
        </Typography>
      </Box>
      <Button variant="text" startIcon={<ArrowBackIcon fontSize="small" />} onClick={onBack}>
        Back to ledger
      </Button>
    </Stack>
  );

  if (error) {
    return (
      <Box className="apps-page" aria-labelledby="apps-title">
        {header}
        <Typography color="error">{error}</Typography>
      </Box>
    );
  }

  if (apps === null) {
    return (
      <Box className="apps-page" aria-labelledby="apps-title">
        {header}
        <Typography color="text.secondary">Loading…</Typography>
      </Box>
    );
  }

  const app = apps.find((a) => a.id === id);

  if (!app) {
    return (
      <Box className="apps-page" aria-labelledby="apps-title">
        {header}
        <Typography color="text.secondary">No application with that id.</Typography>
      </Box>
    );
  }

  const fieldsSubmitted = app.fieldsSubmitted ?? [];
  const confirmation = app.confirmation;
  const screening = app.screening;
  const attachments = app.attachments ?? [];
  const hasEvidence =
    fieldsSubmitted.length > 0 ||
    Boolean(confirmation?.text) ||
    attachments.length > 0 ||
    Boolean(screening?.entity);

  return (
    <Box className="apps-page" aria-labelledby="apps-title">
      {header}

      <Typography variant="h6" sx={{ mb: 2 }}>
        {app.company || "—"}
      </Typography>

      {!hasEvidence ? (
        <Typography color="text.secondary" sx={{ py: 4, textAlign: "center" }}>
          Nothing was recorded for this application.
        </Typography>
      ) : (
        <Stack spacing={4}>
          {fieldsSubmitted.length > 0 && (
            <Box>
              <Typography variant="subtitle1" sx={{ mb: 1 }}>
                Fields submitted
              </Typography>
              <TableContainer className="apps__tablewrap">
                <Table size="small" className="apps__table">
                  <TableHead>
                    <TableRow>
                      <TableCell>Field</TableCell>
                      <TableCell>Value</TableCell>
                      <TableCell>Source</TableCell>
                    </TableRow>
                  </TableHead>
                  <TableBody>
                    {fieldsSubmitted.map((f, i) => (
                      <TableRow key={i}>
                        <TableCell>{f.label || "—"}</TableCell>
                        <TableCell>{f.value || "—"}</TableCell>
                        <TableCell>{f.source || "—"}</TableCell>
                      </TableRow>
                    ))}
                  </TableBody>
                </Table>
              </TableContainer>
            </Box>
          )}

          {confirmation?.text && (
            <Box>
              <Typography variant="subtitle1" sx={{ mb: 1 }}>
                Confirmation
              </Typography>
              <Typography variant="body2">{confirmation.text}</Typography>
              {confirmation.confirmedAt && (
                <Typography variant="body2" color="text.secondary">
                  Confirmed at: {confirmation.confirmedAt}
                </Typography>
              )}
              {confirmation.evidence && (
                <Typography variant="body2" color="text.secondary">
                  Evidence: {confirmation.evidence}
                </Typography>
              )}
            </Box>
          )}

          {attachments.length > 0 && (
            <Box>
              <Typography variant="subtitle1" sx={{ mb: 1 }}>
                Attachments
              </Typography>
              <Stack spacing={0.5}>
                {attachments.map((a, i) => (
                  <Typography key={i} variant="body2">
                    {a.kind || "file"}: {a.path || "—"}
                  </Typography>
                ))}
              </Stack>
            </Box>
          )}

          <Box>
            <Typography variant="subtitle1" sx={{ mb: 1 }}>
              Raw record
            </Typography>
            <Box component="pre" sx={{ p: 2, overflow: "auto", bgcolor: "action.hover", borderRadius: 1 }}>
              {JSON.stringify(
                { fieldsSubmitted, confirmation, screening, attachments },
                null,
                2,
              )}
            </Box>
          </Box>
        </Stack>
      )}
    </Box>
  );
}
