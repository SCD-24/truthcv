import { useState } from "react";
import Box from "@mui/material/Box";
import Button from "@mui/material/Button";
import Dialog from "@mui/material/Dialog";
import DialogActions from "@mui/material/DialogActions";
import DialogContent from "@mui/material/DialogContent";
import DialogTitle from "@mui/material/DialogTitle";
import List from "@mui/material/List";
import ListItem from "@mui/material/ListItem";
import ListItemText from "@mui/material/ListItemText";
import TablePagination from "@mui/material/TablePagination";
import Typography from "@mui/material/Typography";
import { ButtonSpinner } from "../components/ButtonSpinner";
import type { GmailSuggestion } from "../api/types";

export const PAGE_SIZE = 20;

function formatDate(raw: string): string {
  const d = new Date(raw);
  if (!raw || Number.isNaN(d.getTime())) return raw;
  return new Intl.DateTimeFormat(undefined, { dateStyle: "medium" }).format(d);
}

interface Props {
  items: GmailSuggestion[];
  total: number;
  page: number;
  pendingIds: string[];
  bulkBusy: boolean;
  announcement: string;
  onPageChange: (page: number) => void;
  onDismiss: (ids: string[]) => void;
}

/** Pending Gmail suggestions with per-row and bulk dismiss. */
export function GmailSuggestionsList(props: Props) {
  const { items, total, page, pendingIds, bulkBusy, announcement } = props;
  const [confirmOpen, setConfirmOpen] = useState(false);

  return (
    <Box>
      <Typography variant="subtitle1" component="h3">
        Pending suggestions
      </Typography>
      <div aria-live="polite" role="status">
        {announcement}
      </div>
      {items.length === 0 ? (
        <Typography color="text.secondary">No pending suggestions.</Typography>
      ) : (
        <>
          <List>
            {items.map((s) => {
              const busy = pendingIds.includes(s.id);
              return (
                <ListItem
                  key={s.id}
                  secondaryAction={
                    <Button
                      variant="text"
                      disabled={busy || bulkBusy}
                      aria-label={`Dismiss suggestion: ${s.subject}`}
                      onClick={() => props.onDismiss([s.id])}
                    >
                      {busy && <ButtonSpinner />}
                      Dismiss
                    </Button>
                  }
                >
                  <ListItemText
                    primary={s.subject}
                    secondary={`${s.sender} · ${formatDate(s.date)} — ${s.application_label} — ${s.classification} (${s.match_confidence} confidence)`}
                  />
                </ListItem>
              );
            })}
          </List>
          <Button
            variant="outlined"
            disabled={bulkBusy}
            onClick={() => setConfirmOpen(true)}
          >
            {bulkBusy && <ButtonSpinner />}
            Dismiss all on this page
          </Button>
        </>
      )}
      <TablePagination
        component="div"
        count={total}
        page={page}
        rowsPerPage={PAGE_SIZE}
        rowsPerPageOptions={[PAGE_SIZE]}
        onPageChange={(_, p) => props.onPageChange(p)}
      />
      <Dialog open={confirmOpen} onClose={() => setConfirmOpen(false)}>
        <DialogTitle>
          Dismiss {items.length} suggestion{items.length === 1 ? "" : "s"}?
        </DialogTitle>
        <DialogContent>
          <Typography>These suggestions will no longer be shown.</Typography>
        </DialogContent>
        <DialogActions>
          <Button onClick={() => setConfirmOpen(false)}>Cancel</Button>
          <Button
            onClick={() => {
              setConfirmOpen(false);
              props.onDismiss(items.map((s) => s.id));
            }}
          >
            Dismiss
          </Button>
        </DialogActions>
      </Dialog>
    </Box>
  );
}
