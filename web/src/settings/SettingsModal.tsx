import { useEffect, useRef, useState } from "react";
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
import { updateOnboarding } from "../api/client";
import { JobSearchPolicySection } from "./JobSearchPolicySection";
import { SettingsAutosaveProvider, useSettingsAutosaveCoordinator } from "./SettingsAutosave";
import { JevSection } from "./JevSection";
import { GmailSection } from "./GmailSection";
import { useWizard } from "../wizard/store";
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
type ModalProps = {
  onClose: () => void;
  /** Deep link from the Agents page's cooldown summary. */
  initialSection?: "job-search-policy";
};

export function SettingsModal(props: ModalProps) {
  return <SettingsAutosaveProvider><SettingsModalContent {...props} /></SettingsAutosaveProvider>;
}

function SettingsModalContent({ onClose, initialSection }: ModalProps) {
  const autosave = useSettingsAutosaveCoordinator();
  const [closeBlocked, setCloseBlocked] = useState(false);
  const [discarding, setDiscarding] = useState(false);
  const closing = useRef(false);

  async function requestClose(afterFlush?: () => Promise<void>) {
    if (closing.current) return;
    closing.current = true;
    try {
      if (!(await autosave.flushAndWait())) { setCloseBlocked(true); return; }
      if (afterFlush) await afterFlush();
      onClose();
    } finally { closing.current = false; }
  }
  const rootRef = useRef<HTMLDivElement | null>(null);
  const { setOnboarding } = useWizard();

  function replayTour() {
    void requestClose(async () => {
      try {
        setOnboarding(await updateOnboarding({ tourSeenAt: null }));
      } catch (err) {
        console.error("Failed to reset tour state", err);
      }
    });
  }

  useEffect(() => {
    if (initialSection !== "job-search-policy") return;
    const el = rootRef.current?.querySelector<HTMLElement>("#job-search-policy-section");
    el?.scrollIntoView({ block: "center" });
  }, [initialSection]);

  return (
    <Dialog open onClose={() => { void requestClose(); }} maxWidth="md" fullWidth aria-labelledby="settings-title">
      <DialogTitle
        id="settings-title"
        sx={{ display: "flex", alignItems: "center", justifyContent: "space-between" }}
      >
        Settings
        <IconButton onClick={() => { void requestClose(); }} aria-label="Close settings" edge="end">
          <CloseIcon />
        </IconButton>
      </DialogTitle>

      <DialogContent dividers ref={rootRef}>
        <fieldset disabled={discarding} style={{ border: 0, margin: 0, padding: 0, minWidth: 0 }}>
        <Stack spacing={3}>
            <JobSearchPolicySection />

            <JevSection />

            <GmailSection />

            <SettingsSection
              title="Replay tour"
              description="Walk through the guided tour of the manual and agent flows again."
            >
              <Button variant="outlined" onClick={replayTour} sx={{ alignSelf: "flex-start" }}>
                Replay tour
              </Button>
            </SettingsSection>
          </Stack>
        </fieldset>
      </DialogContent>

      <DialogActions>
        {closeBlocked && (
          <Alert severity="error" role="alert">
            Unsaved or invalid changes remain. Fix them or discard changes to close.
          </Alert>
        )}
        {closeBlocked && <Button disabled={discarding} onClick={async () => {
          if (closing.current) return;
          closing.current = true;
          setDiscarding(true);
          await autosave.discardAndWait();
          onClose();
        }}>Discard changes</Button>}
        <Button disabled={discarding} onClick={() => { void requestClose(); }}>Close</Button>
      </DialogActions>
    </Dialog>
  );
}
