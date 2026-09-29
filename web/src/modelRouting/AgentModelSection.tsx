import { updateRouting } from "../api/client";
import { ModelRoutePicker } from "../settings/ModelRoutePicker";
import type { ConnectionStatus, Routing } from "../api/types";

/** Per-stage agent overrides. Mirrors modelrouting.AGENT_STAGE_NAMES (and agent/harness/stages.ts). */
export const AGENT_STAGES = [
  { key: "screening", label: "Agent screening", description: "Screens discovered postings before applying. Falls back to the agent model." },
  { key: "extract", label: "Agent extraction", description: "Extracts posting details for the agent. Falls back to the agent model." },
] as const;

/** Agent routing is independent of the manual CV task default. */
export function AgentModelSection({ connections, routing, onSaved }: {
  connections: ConnectionStatus[];
  routing: Routing;
  onSaved: (routing: Routing) => void;
}) {
  return <>
    <ModelRoutePicker
      connections={connections}
      route={routing.agent}
      autosaveKey="routing:agent"
      onSave={async (route) => onSaved(await updateRouting({ agent: route }))}
      title="Application agent"
      description="Runs unattended job applications in the browser, independently of task models. When unset, it uses Claude independently of the task default, using a saved Claude sign-in or API key with an environment credential fallback. Changes take effect on the next run."
      filterCards={["claude", "openrouter", "codex"]}
      allowClear
    />
    {AGENT_STAGES.map(({ key, label, description }) => (
      <ModelRoutePicker
        key={key}
        connections={connections}
        route={routing.agentStages?.[key] ?? null}
        autosaveKey={`routing:agentStage:${key}`}
        onSave={async (route) => onSaved(await updateRouting({ agentStages: { [key]: route } }))}
        title={label}
        description={description}
        allowClear
        showTest={false}
      />
    ))}
  </>;
}
