import { ROUTES } from "../routes";

export interface TourStep {
  id: string;
  anchor: string; // matches a data-tour attribute value
  title: string;
  body: string;
  navigateTo?: string; // a ROUTES value, if this step lives on another page
}

/**
 * The guided tour, in narrative order: first the hands-on "manual" process
 * (paste a posting, pick what to generate, optionally file a record, then find
 * the result under Applications), then the automated "agent" process (agents
 * run, produce screenings, and surface approvals). Each step's `anchor` matches
 * a `data-tour` attribute already present in the DOM; steps that live on
 * another page carry a `navigateTo` so the tour can route there first.
 */
export const TOUR_STEPS: TourStep[] = [
  {
    id: "manual-link",
    anchor: "nav-manual",
    title: "Start with Manual",
    body: "The Manual page is where you tailor a CV or cover letter to a single job posting, by hand and on demand.",
    navigateTo: ROUTES.manual,
  },
  {
    id: "manual-posting",
    anchor: "manual-posting",
    title: "Paste the posting",
    body: "Drop the full job description here. We tailor to it using only the facts in your truth file — nothing invented.",
  },
  {
    id: "manual-outputs",
    anchor: "manual-outputs",
    title: "Choose what to generate",
    body: "Pick a tailored CV, a cover letter, or both. Each document is built from the same verified source facts.",
  },
  {
    id: "manual-record",
    anchor: "manual-record",
    title: "File a record (optional)",
    body: "Say yes to create an application record for this posting, so the documents you generate stay attached to it.",
  },
  {
    id: "applications-link",
    anchor: "nav-applications",
    title: "Find it under Applications",
    body: "Every record you create shows up here, with its posting and attached documents kept together.",
    navigateTo: ROUTES.applications,
  },
  {
    id: "agents-link",
    anchor: "nav-agents",
    title: "Let Agents do the work",
    body: "Agents automate the same process — they watch for postings and tailor applications for you without the manual steps.",
    navigateTo: ROUTES.agents,
  },
  {
    id: "screenings-link",
    anchor: "nav-screenings",
    title: "Review Screenings",
    body: "As agents run, they produce screenings — their read on how well a posting fits your truth file.",
    navigateTo: ROUTES.screenings,
  },
  {
    id: "approvals-link",
    anchor: "nav-approvals",
    title: "Sign off in Approvals",
    body: "Anything an agent needs you to confirm lands here. Nothing goes out until you approve it.",
    navigateTo: ROUTES.approvals,
  },
];
