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
import Stack from "@mui/material/Stack";
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

function capitalise(s: string): string {
  return s.charAt(0).toUpperCase() + s.slice(1);
}

interface Props {
  items: GmailSuggestion[];
  total: number;
  page: number;
  pendingIds: string[];
  bulkBusy: boolean;
  onPageChange: (page: number) => void;
  onDismiss: (ids: string[]) => void;
  onAccept: (item: GmailSuggestion) => void;
}

interface RowProps {
  item: GmailSuggestion;
  busy: boolean;
  disabled: boolean;
  onDismiss: (ids: string[]) => void;
  onAccept: (item: GmailSuggestion) => void;
}

function RowActions({ item, busy, disabled, onDismiss, onAccept }: RowProps) {
  return (
    <Stack direction="row" spacing={1}>
      {item.suggested_status && (
        <Button
          variant="contained"
          disabled={disabled}
          aria-label={`Mark ${item.suggested_status}: ${item.subject}`}
          onClick={() => onAccept(item)}
        >
          {busy && <ButtonSpinner />}
          Mark {item.suggested_status}
        </Button>
      )}
      <Button
        variant="text"
        disabled={disabled}
        aria-label={`Dismiss: ${item.subject}`}
        onClick={() => onDismiss([item.id])}
      >
        {busy && <ButtonSpinner />}
        Dismiss
      </Button>
    </Stack>
  );
}

function EmailResponseRow(props: RowProps) {
  const { item } = props;
  return (
    <ListItem sx={{ gap: 2, flexWrap: "wrap", alignItems: "flex-start" }}>
      <ListItemText
        sx={{ minWidth: 0, flex: "1 1 16rem", overflowWrap: "anywhere" }}
        primary={item.subject}
        secondary={
          <>
            {`${item.sender} · ${formatDate(item.date)} — ${item.application_label}`}
            <br />
            {`${capitalise(item.classification)} · ${item.match_confidence} confidence`}
          </>
        }
      />
      <RowActions {...props} />
    </ListItem>
  );
}

function dismissBody(items: GmailSuggestion[]): string {
  const n = items.filter((s) => s.suggested_status).length;
  if (n === 0) return "These email responses will no longer be shown.";
  return `${n} of these would change an application's status. Dismissing them means you'll update those applications yourself.`;
}

/** Pending email responses with per-row accept/dismiss and bulk dismiss. */
export function EmailResponsesList(props: Props) {
  const { items, total, page, pendingIds, bulkBusy } = props;
  const [confirmOpen, setConfirmOpen] = useState(false);

  return (
    <Box>
      {items.length > 0 && (
        <>
          <List>
            {items.map((s) => (
              <EmailResponseRow
                key={s.id}
                item={s}
                busy={pendingIds.includes(s.id)}
                disabled={pendingIds.includes(s.id) || bulkBusy}
                onDismiss={props.onDismiss}
                onAccept={props.onAccept}
              />
            ))}
          </List>
          <Button variant="outlined" disabled={bulkBusy} onClick={() => setConfirmOpen(true)}>
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
          Dismiss {items.length} email response{items.length === 1 ? "" : "s"}?
        </DialogTitle>
        <DialogContent>
          <Typography>{dismissBody(items)}</Typography>
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
