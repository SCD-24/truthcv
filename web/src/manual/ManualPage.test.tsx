// @vitest-environment jsdom
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import {
  confirmInferences,
  createApplication,
  generateCoverLetter,
  listApplications,
  listPromptPresets,
  render as apiRender,
  tailor,
} from "../api/client";
import type { Application } from "../api/types";
import { ManualPage } from "./ManualPage";

vi.mock("../api/client", () => ({
  tailor: vi.fn(),
  confirmInferences: vi.fn(),
  render: vi.fn(),
  generateCoverLetter: vi.fn(),
  createApplication: vi.fn(),
  listApplications: vi.fn(),
  listPromptPresets: vi.fn(),
  saveApplicationCv: vi.fn(),
  saveApplicationCoverLetter: vi.fn(),
}));

// DocumentEditor reads `posting` off the wizard store; the page itself holds all
// of its own state locally, so a stub store is all the tree needs.
vi.mock("../wizard/store", () => ({
  useWizard: vi.fn(() => ({ posting: "" })),
}));

/** Render the page inside a router — the style picker links to /writing-style. */
function renderPage() {
  return render(
    <MemoryRouter>
      <ManualPage />
    </MemoryRouter>,
  );
}

beforeEach(() => {
  vi.mocked(createApplication).mockResolvedValue({ id: "app-123" } as Application);
  vi.mocked(tailor).mockResolvedValue({ keywords: [], inferences: [] });
  vi.mocked(confirmInferences).mockResolvedValue(undefined);
  vi.mocked(apiRender).mockResolvedValue({
    blocked: false,
    unverifiable: [],
    blockedClaims: [],
    atsWarnings: [],
    pdfUrl: null,
    docxUrl: null,
    html: "<p>cv</p>",
  });
  vi.mocked(generateCoverLetter).mockResolvedValue({
    blocked: false,
    unverifiable: [],
    blockedClaims: [],
    pdfUrl: null,
    docxUrl: null,
    text: "Dear hiring manager…",
  });
  vi.mocked(listApplications).mockResolvedValue([]);
  vi.mocked(listPromptPresets).mockResolvedValue([
    { id: "professional", name: "Professional", fragmentIds: [], isDefault: true, seeded: true },
    { id: "warm", name: "Warm", fragmentIds: [], isDefault: false, seeded: true },
    { id: "concise", name: "Concise", fragmentIds: [], isDefault: false, seeded: true },
  ]);
});

afterEach(() => {
  cleanup();
  vi.clearAllMocks();
});

/** Fill the four company fields and the posting textarea. */
function fillForm() {
  fireEvent.change(screen.getByLabelText(/job posting/i), {
    target: { value: "Senior engineer wanted" },
  });
  fireEvent.change(screen.getByLabelText(/company/i), { target: { value: "Acme" } });
  fireEvent.change(screen.getByLabelText(/^role/i), { target: { value: "Engineer" } });
  fireEvent.change(screen.getByLabelText(/website/i), {
    target: { value: "https://acme.test" },
  });
  fireEvent.change(screen.getByLabelText(/application url/i), {
    target: { value: "https://acme.test/apply" },
  });
}

function submitButton() {
  return screen.getByRole("button", { name: "Generate" }) as HTMLButtonElement;
}

function checkbox(name: string) {
  return screen.getByRole("checkbox", { name }) as HTMLInputElement;
}

/** Drive the CV path to a rendered document: submit, confirm, wait for render. */
async function runCvThenLetter() {
  fireEvent.click(submitButton());
  fireEvent.click(await screen.findByRole("button", { name: "Confirm & continue" }));
  fireEvent.click(await screen.findByRole("button", { name: "Generate cover letter" }));
}

describe("ManualPage", () => {
  it("disables submit until posting, all four company fields, and an output are set", () => {
    renderPage();
    // Empty form: disabled.
    expect(submitButton().disabled).toBe(true);

    // All fields filled, CV checked by default: enabled.
    fillForm();
    expect(submitButton().disabled).toBe(false);

    // Uncheck the only selected output: disabled again.
    fireEvent.click(checkbox("Tailor my CV"));
    expect(submitButton().disabled).toBe(true);

    // Check the other output: enabled once more.
    fireEvent.click(checkbox("Write a cover letter"));
    expect(submitButton().disabled).toBe(false);
  });

  it("creates an application record exactly once when 'Yes' is chosen", async () => {
    renderPage();
    fillForm();
    fireEvent.click(screen.getByRole("radio", { name: "Yes" }));
    fireEvent.click(submitButton());

    await screen.findByRole("button", { name: "Confirm & continue" });
    expect(createApplication).toHaveBeenCalledTimes(1);
    expect(createApplication).toHaveBeenCalledWith({
      company: "Acme",
      website: "https://acme.test",
      applicationUrl: "https://acme.test/apply",
      posting: "Senior engineer wanted",
    });
  });

  it("never creates a record when 'No' is chosen", async () => {
    renderPage();
    fillForm();
    fireEvent.click(submitButton()); // default toggle is No

    // Wait for the CV path to start, proving submit was processed.
    await screen.findByRole("button", { name: "Confirm & continue" });
    expect(createApplication).not.toHaveBeenCalled();
  });

  it("never tailors or confirms inferences when only a cover letter is requested", async () => {
    renderPage();
    fillForm();
    fireEvent.click(checkbox("Tailor my CV")); // uncheck CV
    fireEvent.click(checkbox("Write a cover letter")); // check letter
    fireEvent.click(submitButton());

    await screen.findByRole("button", { name: "Generate cover letter" });
    expect(tailor).not.toHaveBeenCalled();
    expect(confirmInferences).not.toHaveBeenCalled();
  });

  it("loads presets on mount and defaults the style picker to the default preset", async () => {
    renderPage();
    fillForm();
    fireEvent.click(checkbox("Tailor my CV")); // uncheck CV
    fireEvent.click(checkbox("Write a cover letter")); // check letter
    fireEvent.click(submitButton());

    await screen.findByRole("button", { name: "Generate cover letter" });
    await waitFor(() => expect(listPromptPresets).toHaveBeenCalledTimes(1));
    const profesButton = await screen.findByRole("button", { name: "Professional" });
    expect((profesButton as HTMLButtonElement).getAttribute("aria-pressed")).toBe("true");
  });

  it("passes the created record's id to both render and generateCoverLetter, sending the default preset id as tone", async () => {
    renderPage();
    fillForm();
    fireEvent.click(checkbox("Write a cover letter")); // both CV + letter
    fireEvent.click(screen.getByRole("radio", { name: "Yes" }));
    await runCvThenLetter();

    await waitFor(() =>
      expect(generateCoverLetter).toHaveBeenCalledWith(
        "professional",
        "standard",
        undefined,
        "app-123",
        "Senior engineer wanted",
        "professional",
      ),
    );
    expect(apiRender).toHaveBeenCalledWith(undefined, "app-123");
  });

  it("passes applicationId as undefined when no record was created", async () => {
    renderPage();
    fillForm();
    fireEvent.click(checkbox("Write a cover letter")); // both CV + letter, toggle stays No
    await runCvThenLetter();

    await waitFor(() =>
      expect(generateCoverLetter).toHaveBeenCalledWith(
        "professional",
        "standard",
        undefined,
        undefined,
        "Senior engineer wanted",
        "professional",
      ),
    );
    expect(apiRender).toHaveBeenCalledWith(undefined, undefined);
  });

  it("sends the typed posting even on the letter-only path (no tailor call)", async () => {
    renderPage();
    fillForm();
    fireEvent.click(checkbox("Tailor my CV")); // uncheck CV
    fireEvent.click(checkbox("Write a cover letter")); // check letter
    fireEvent.click(submitButton());

    await screen.findByRole("button", { name: "Generate cover letter" });
    fireEvent.click(screen.getByRole("button", { name: "Generate cover letter" }));

    await waitFor(() =>
      expect(generateCoverLetter).toHaveBeenCalledWith(
        "professional",
        "standard",
        undefined,
        undefined,
        "Senior engineer wanted",
        "professional",
      ),
    );
    expect(tailor).not.toHaveBeenCalled();
  });
});
