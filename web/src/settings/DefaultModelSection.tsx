import { updateRouting } from "../api/client";
import { ModelRoutePicker } from "./ModelRoutePicker";
import type { ConnectionStatus, Routing } from "../api/types";

/** The "which model runs by default" section: pick a connected provider, pick
 * (or type) a model, save it as the routing default, and test it. */
export function DefaultModelSection({
  connections,
  routing,
  onSaved,
}: {
  connections: ConnectionStatus[];
  routing: Routing;
  onSaved: (r: Routing) => void;
}) {
  return (
    <ModelRoutePicker
      connections={connections}
      route={routing.default}
      onSave={async (route) => {
        const fresh = await updateRouting({ default: route });
        onSaved(fresh);
      }}
      title="Default model"
      description="The model used when a task has no more specific routing."
      showTest
    />
  );
}
