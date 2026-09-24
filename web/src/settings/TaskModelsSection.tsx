import { updateRouting } from "../api/client";
import { ModelRoutePicker } from "./ModelRoutePicker";
import { SettingsSection } from "./SettingsModal";
import { SettingsAutosaveProvider, useHasSettingsAutosaveProvider } from "./SettingsAutosave";
import type { ConnectionStatus, Routing } from "../api/types";

/** The task keys the backend routes independently, paired with the label each
 * row shows. Mirrors `modelrouting.TASK_NAMES` (modelrouting/store.py) — same
 * drift-protection pattern as CONNECTION_MODES for the mode literals. */
export const TASKS = [
  { key: "truth_extract", label: "Truth extraction", description: "Extracts factual career information from your uploaded profile." },
  { key: "keywords", label: "Keyword extraction", description: "Identifies relevant skills and keywords in the job posting." },
  { key: "tailor", label: "CV tailoring", description: "Selects and rephrases your verified experience for the target role." },
  { key: "infer", label: "Inference detection", description: "Suggests claims not yet in your verified profile for you to review." },
  { key: "cover_letter", label: "Cover letter", description: "Drafts a cover letter tailored to the job posting." },
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
  const hasProvider = useHasSettingsAutosaveProvider();
  const rows = (
    <SettingsSection
      title="Task models"
      description="Overrides the default model per task; cleared tasks use the default."
    >
      {TASKS.map(({ key, label, description }) => (
        <ModelRoutePicker
          key={key}
          connections={connections}
          route={routing.tasks[key] ?? null}
          autosaveKey={`routing:${key}`}
          onSave={async (route) => {
            const fresh = await updateRouting({ tasks: { [key]: route } });
            onSaved(fresh);
          }}
          title={label}
          description={description}
          allowClear
          showTest={false}
        />
      ))}
    </SettingsSection>
  );
  return hasProvider ? rows : <SettingsAutosaveProvider>{rows}</SettingsAutosaveProvider>;
}
