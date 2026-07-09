export type StepId = "upload" | "review" | "posting" | "confirm" | "download";

export interface StepDef {
  id: StepId;
  label: string;
}

/** The wizard, in order. The rail renders this as a record of progress. */
export const STEPS: StepDef[] = [
  { id: "upload", label: "Upload" },
  { id: "review", label: "Review" },
  { id: "posting", label: "Posting" },
  { id: "confirm", label: "Confirm" },
  { id: "download", label: "Download" },
];

export const stepIndex = (id: StepId): number =>
  STEPS.findIndex((s) => s.id === id);

/** Props every step component receives from the shell. */
export interface StepProps {
  onAdvance: (to: StepId) => void;
  onBack: (to: StepId) => void;
}
