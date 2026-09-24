import { updateRouting } from "../api/client";
import { ModelRoutePicker } from "../settings/ModelRoutePicker";
import type { ConnectionStatus, Routing } from "../api/types";

/** Agent routing is independent of the manual CV task default. */
export function AgentModelSection({ connections, routing, onSaved }: {
  connections: ConnectionStatus[];
  routing: Routing;
  onSaved: (routing: Routing) => void;
}) {
  return <ModelRoutePicker
    connections={connections}
    route={routing.agent}
    autosaveKey="routing:agent"
    onSave={async (route) => onSaved(await updateRouting({ agent: route }))}
    title="Application agent"
    description="Runs unattended job applications in the browser, independently of task models. When unset, it uses Claude independently of the task default, using a saved Claude sign-in or API key with an environment credential fallback. Changes take effect on the next run."
    filterCards={["claude", "openrouter", "codex"]}
    allowClear
  />;
}
