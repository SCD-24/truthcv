import { updateRouting } from "../api/client";
import { ModelRoutePicker } from "./ModelRoutePicker";
import { SettingsSection } from "./SettingsModal";
import type { ConnectionStatus, Routing } from "../api/types";

/** The task keys the backend routes independently (providers/__init__.py's
 * get_provider(task) callers), paired with the label each row shows. Mirrors
 * the backend's task-name strings — same drift-protection pattern as
 * CONNECTION_MODES for the mode literals. */
export const TASKS = [
  { key: "truth_extract", label: "Truth extraction" },
  { key: "keywords", label: "Keyword extraction" },
  { key: "tailor", label: "CV tailoring" },
  { key: "infer", label: "Inference detection" },
  { key: "cover_letter", label: "Cover letter" },
] as const;

/** The "override the default model per task" section: one ModelRoutePicker
 * row per task, each saving/clearing just that task's route. */
export function TaskModelsSection({
  connections,
  routing,
  onSaved,
}: {
  connections: ConnectionStatus[];
  routing: Routing;
  onSaved: (r: Routing) => void;
}) {
  return (
    <SettingsSection
      title="Task models"
      description="Overrides the default model per task; cleared tasks use the default."
    >
      {TASKS.map(({ key, label }) => (
        <ModelRoutePicker
          key={key}
          connections={connections}
          route={routing.tasks[key] ?? null}
          onSave={async (route) => {
            const fresh = await updateRouting({ tasks: { [key]: route } });
            onSaved(fresh);
          }}
          title={label}
          allowClear
          showTest={false}
        />
      ))}
    </SettingsSection>
  );
}
