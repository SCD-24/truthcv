import { createContext, useCallback, useContext, useEffect, useState } from "react";
import type { ReactNode } from "react";
import { useLocation } from "react-router-dom";
import Alert from "@mui/material/Alert";
import Button from "@mui/material/Button";
import Stack from "@mui/material/Stack";
import { SettingsAutosaveProvider, useSettingsAutosaveCoordinator } from "../settings/SettingsAutosave";

const ReloadContext = createContext({ revision: 0, complete: (_revision: number) => {} });
/** A discard remounts the page only after an in-flight server mutation finishes. */
export function useModelRoutingReload() { return useContext(ReloadContext).revision; }
/** Unlock routing only when the post-discard GET has supplied a fresh page. */
export function useModelRoutingReloadComplete() { return useContext(ReloadContext).complete; }

/** Keep the routing write queue mounted in the app shell, not in the route. */
export function ModelRoutingSession({ children }: { children: ReactNode }) {
  return <SettingsAutosaveProvider><SessionContent>{children}</SessionContent></SettingsAutosaveProvider>;
}

function SessionContent({ children }: { children: ReactNode }) {
  const coordinator = useSettingsAutosaveCoordinator();
  const { pathname } = useLocation();
  const [outstanding, setOutstanding] = useState(() => coordinator.outstanding());
  const [discarding, setDiscarding] = useState(false);
  const [reload, setReload] = useState(0);
  useEffect(() => coordinator.subscribe(() => setOutstanding(coordinator.outstanding())), [coordinator]);
  useEffect(() => { coordinator.flush(); }, [coordinator, pathname]);
  useEffect(() => {
    const warn = (event: BeforeUnloadEvent) => {
      if (!coordinator.outstanding().length) return;
      event.preventDefault();
      event.returnValue = "";
    };
    window.addEventListener("beforeunload", warn);
    return () => window.removeEventListener("beforeunload", warn);
  }, [coordinator]);

  const complete = useCallback((revision: number) => {
    if (revision > 0 && revision === reload && coordinator.isDiscarding()) {
      coordinator.endDiscard();
      setDiscarding(false);
    }
  }, [coordinator, reload]);

  async function discard() {
    setDiscarding(true);
    await coordinator.discardAndWait();
    setReload((value) => value + 1);
  }

  return <ReloadContext.Provider value={{ revision: reload, complete }}>
    {outstanding.length > 0 && <Alert severity="warning" role="alert">
      <Stack spacing={1}>
        <span>Model routing changes need attention.</span>
        {outstanding.map(({ key, status, error }) =>
          <Stack key={key} direction="row" spacing={1} sx={{ alignItems: "center" }}>
            <span>{key.replace("routing:", "")}: {status}{error ? ` — ${error}` : ""}</span>
            {status === "error" && <Button disabled={discarding} onClick={() => coordinator.retry(key)}>Retry save</Button>}
          </Stack>,
        )}
        <Button disabled={discarding} onClick={() => { void discard(); }}>Discard routing changes</Button>
      </Stack>
    </Alert>}
    {children}
  </ReloadContext.Provider>;
}
