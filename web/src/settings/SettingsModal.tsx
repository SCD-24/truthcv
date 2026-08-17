import { useEffect, useState } from "react";
import type { ReactNode } from "react";
import Dialog from "@mui/material/Dialog";
import DialogTitle from "@mui/material/DialogTitle";
import DialogContent from "@mui/material/DialogContent";
import DialogActions from "@mui/material/DialogActions";
import Stack from "@mui/material/Stack";
import Button from "@mui/material/Button";
import IconButton from "@mui/material/IconButton";
import CloseIcon from "@mui/icons-material/Close";
import Alert from "@mui/material/Alert";
import Typography from "@mui/material/Typography";
import { getRouting, listConnections } from "../api/client";
import { AccountsSection } from "./AccountsSection";
import { DefaultModelSection } from "./DefaultModelSection";
import { TaskModelsSection } from "./TaskModelsSection";
import type { ConnectionList, Routing } from "../api/types";
import "../styles/settings.css";

/** A titled group of settings fields, separated from its siblings by a
 * Divider in the caller. Establishes the one section pattern the modal's
 * panels share. Exported so other settings panels (e.g. AccountsSection)
 * reuse the same wrapper instead of duplicating it. */
export function SettingsSection({
  title,
  description,
  children,
}: {
  title: string;
  description?: string;
  children: ReactNode;
}) {
  return (
    <Stack spacing={2}>
      <Stack spacing={0.5}>
        <Typography variant="h6">{title}</Typography>
        {description && (
          <Typography variant="body2" color="text.secondary">
            {description}
          </Typography>
        )}
      </Stack>
      <Stack spacing={2}>{children}</Stack>
    </Stack>
  );
}

/**
 * The connections + routing settings modal, opened from the rail's Settings
 * control. Loads the provider connection list and current routing on open,
 * and renders the Accounts section (connect/disconnect providers) and the
 * Default model section (pick and save the default routing).
 */
export function SettingsModal({ onClose }: { onClose: () => void }) {
  const [connections, setConnections] = useState<ConnectionList | null>(null);
  const [routing, setRouting] = useState<Routing | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  function refetchConnections() {
    listConnections()
      .then(setConnections)
      .catch((e: unknown) =>
        setError(e instanceof Error ? e.message : "Couldn't load connections."),
      );
  }

  // Load connections + routing once when the modal opens.
  useEffect(() => {
    let alive = true;
    Promise.all([listConnections(), getRouting()])
      .then(([c, r]) => {
        if (!alive) return;
        setConnections(c);
        setRouting(r);
      })
      .catch((e: unknown) =>
        setError(e instanceof Error ? e.message : "Couldn't load settings."),
      )
      .finally(() => alive && setLoading(false));
    return () => {
      alive = false;
    };
  }, []);

  const encryptionOff = connections ? !connections.encryptionAvailable : false;

  return (
    <Dialog open onClose={onClose} maxWidth="md" fullWidth aria-labelledby="settings-title">
      <DialogTitle
        id="settings-title"
        sx={{ display: "flex", alignItems: "center", justifyContent: "space-between" }}
      >
        Settings
        <IconButton onClick={onClose} aria-label="Close settings" edge="end">
          <CloseIcon />
        </IconButton>
      </DialogTitle>

      <DialogContent dividers>
        {loading ? (
          <Typography color="text.secondary" sx={{ py: 2 }}>
            Loading settings…
          </Typography>
        ) : (
          <Stack spacing={3}>
            {encryptionOff && (
              <Alert severity="warning">
                Set <code>ENCRYPTION_KEY</code> in your <code>.env</code> to save
                keys securely. Until then TruthCV falls back to keys in the
                environment.
              </Alert>
            )}
            {error && <Alert severity="error">{error}</Alert>}

            {connections && (
              <AccountsSection list={connections} onChanged={refetchConnections} />
            )}

            {connections && routing && (
              <DefaultModelSection
                connections={connections.connections}
                routing={routing}
                onSaved={setRouting}
              />
            )}

            {connections && routing && (
              <TaskModelsSection
                connections={connections.connections}
                routing={routing}
                onSaved={setRouting}
              />
            )}
          </Stack>
        )}
      </DialogContent>

      <DialogActions>
        <Button onClick={onClose}>Close</Button>
      </DialogActions>
    </Dialog>
  );
}
