import { useEffect, useRef, useState } from "react";
import Alert from "@mui/material/Alert";
import Button from "@mui/material/Button";
import Stack from "@mui/material/Stack";
import Typography from "@mui/material/Typography";
import { getRouting, listConnections } from "../api/client";
import type { ConnectionList, Routing } from "../api/types";
import { AccountsSection } from "../settings/AccountsSection";
import { DefaultModelSection } from "../settings/DefaultModelSection";
import { TaskModelsSection } from "../settings/TaskModelsSection";
import { useModelRoutingReload, useModelRoutingReloadComplete } from "./ModelRoutingSession";
import { useSettingsAutosaveCoordinator } from "../settings/SettingsAutosave";
import { AgentModelSection } from "./AgentModelSection";

/** One address for provider accounts and all independently routed model choices. */
export function ModelRoutingPage() {
  const reload = useModelRoutingReload();
  const completeReload = useModelRoutingReloadComplete();
  const coordinator = useSettingsAutosaveCoordinator();
  const connectionRequest = useRef(0);
  const mounted = useRef(false);
  const [attempt, setAttempt] = useState(0);
  const [connections, setConnections] = useState<ConnectionList | null>(null);
  const [routing, setRouting] = useState<Routing | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [connectionError, setConnectionError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    mounted.current = true;
    const request = ++connectionRequest.current;
    const readStartedAt = coordinator.beginRoutingRead();
    setLoading(true);
    setConnections(null);
    setRouting(null);
    setError(null);
    Promise.all([listConnections(), getRouting()]).then(([list, routes]) => {
      if (!mounted.current || request !== connectionRequest.current) return;
      coordinator.acceptRoutingRead(readStartedAt);
      setConnections(list);
      setRouting(routes);
      completeReload(reload);
    }).catch((e: unknown) => {
      if (mounted.current && request === connectionRequest.current) {
        setError(e instanceof Error ? e.message : "Couldn't load model routing.");
      }
    }).finally(() => {
      if (mounted.current && request === connectionRequest.current) setLoading(false);
    });
    return () => { mounted.current = false; connectionRequest.current++; };
  }, [attempt, reload, coordinator, completeReload]);

  function refreshConnections() {
    const request = ++connectionRequest.current;
    listConnections().then((list) => {
      if (!mounted.current || request !== connectionRequest.current) return;
      setConnections(list);
      setConnectionError(null);
    }).catch((e: unknown) => {
      if (mounted.current && request === connectionRequest.current) {
        setConnectionError(e instanceof Error ? e.message : "Couldn't refresh accounts.");
      }
    });
  }

  return <Stack spacing={3} aria-label="Model routing">
    <Typography variant="h4" component="h1">Model routing</Typography>
    {loading && <Typography role="status">Loading model routing…</Typography>}
    {error && <Alert severity="error">{error} <Button onClick={() => setAttempt((value) => value + 1)}>Retry loading</Button></Alert>}
    {connectionError && <Alert severity="error">{connectionError} <Button onClick={refreshConnections}>Retry accounts</Button></Alert>}
    {connections && routing && <>
      {!connections.encryptionAvailable && <Alert severity="warning">Set <code>ENCRYPTION_KEY</code> in your <code>.env</code> to save keys securely. Until then TruthCV falls back to keys in the environment.</Alert>}
      <AccountsSection list={connections} onChanged={refreshConnections} />
      <DefaultModelSection connections={connections.connections} routing={routing} onSaved={setRouting} autosave />
      <TaskModelsSection connections={connections.connections} routing={routing} onSaved={setRouting} />
      <AgentModelSection connections={connections.connections} routing={routing} onSaved={setRouting} />
    </>}
  </Stack>;
}
