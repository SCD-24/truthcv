// @vitest-environment jsdom
/** DocumentEditor: dirty tracking / beforeunload guard, and the applications
 * load-failure alert. */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { DocumentEditor } from "./DocumentEditor";
import { listApplications, saveApplicationCv } from "../api/client";
import type { SaveDocumentResult } from "../api/types";

vi.mock("../api/client", () => ({
  listApplications: vi.fn(),
  createApplication: vi.fn(),
  saveApplicationCv: vi.fn(),
  saveApplicationCoverLetter: vi.fn(),
}));

// DocumentEditor reads `posting` off the wizard store; a stub store avoids
// mounting the real WizardProvider, which would otherwise fire its own
// (unmocked) startup bootstrap effect against ../api/client.
vi.mock("../wizard/store", () => ({
  useWizard: vi.fn(() => ({ posting: "" })),
}));

function renderEditor(onDirtyChange?: (dirty: boolean) => void) {
  return render(<DocumentEditor kind="cv" initial="Hello" onDirtyChange={onDirtyChange} />);
}

beforeEach(() => {
  vi.mocked(listApplications).mockResolvedValue([]);
});

afterEach(() => {
  cleanup();
  vi.clearAllMocks();
});

describe("DocumentEditor dirty tracking", () => {
  it("prevents beforeunload once the content has changed", async () => {
    renderEditor();
    await waitFor(() => expect(listApplications).toHaveBeenCalled());

    fireEvent.change(screen.getByLabelText(/edit cv/i), { target: { value: "Changed" } });

    const event = new Event("beforeunload", { cancelable: true });
    window.dispatchEvent(event);
    expect(event.defaultPrevented).toBe(true);
  });

  it("does not prevent beforeunload while clean", async () => {
    renderEditor();
    await waitFor(() => expect(listApplications).toHaveBeenCalled());

    const event = new Event("beforeunload", { cancelable: true });
    window.dispatchEvent(event);
    expect(event.defaultPrevented).toBe(false);
  });
});

describe("DocumentEditor applications load failure", () => {
  it("shows a Retry alert when listApplications fails", async () => {
    vi.mocked(listApplications).mockRejectedValue(new Error("boom"));
    renderEditor();

    expect(await screen.findByText(/couldn't load your applications/i)).toBeTruthy();
    expect(screen.getByRole("button", { name: /retry/i })).toBeTruthy();
  });
});

describe("DocumentEditor dirty tracking after save", () => {
  function isDirty(): boolean {
    const event = new Event("beforeunload", { cancelable: true });
    window.dispatchEvent(event);
    return event.defaultPrevented;
  }

  it("is dirty again after saving B then reverting the text back to A", async () => {
    vi.mocked(saveApplicationCv).mockResolvedValue({
      blocked: false,
      application: { id: "app1", company: "Acme" },
    } as never);
    render(<DocumentEditor kind="cv" initial="Hello" lockedAppId="app1" />);
    await waitFor(() => expect(listApplications).toHaveBeenCalled());

    fireEvent.change(screen.getByLabelText(/edit cv/i), { target: { value: "B" } });
    expect(isDirty()).toBe(true);

    fireEvent.click(screen.getByRole("button", { name: /save cv to application/i }));
    await waitFor(() => expect(saveApplicationCv).toHaveBeenCalledWith("app1", "B"));
    await waitFor(() => expect(isDirty()).toBe(false));

    fireEvent.change(screen.getByLabelText(/edit cv/i), { target: { value: "Hello" } });
    expect(isDirty()).toBe(true);
  });

  it("stays dirty when the content is edited again while a save is in flight", async () => {
    const deferred: { resolve?: (v: SaveDocumentResult) => void } = {};
    vi.mocked(saveApplicationCv).mockImplementation(
      () =>
        new Promise<SaveDocumentResult>((resolve) => {
          deferred.resolve = resolve;
        }),
    );
    render(<DocumentEditor kind="cv" initial="Hello" lockedAppId="app1" />);
    await waitFor(() => expect(listApplications).toHaveBeenCalled());

    fireEvent.change(screen.getByLabelText(/edit cv/i), { target: { value: "typing1" } });
    fireEvent.click(screen.getByRole("button", { name: /save cv to application/i }));
    await waitFor(() => expect(saveApplicationCv).toHaveBeenCalledWith("app1", "typing1"));

    // Edit again while that save is still outstanding.
    fireEvent.change(screen.getByLabelText(/edit cv/i), { target: { value: "typing2" } });

    deferred.resolve?.({
      blocked: false,
      application: { id: "app1", company: "Acme" },
    } as SaveDocumentResult);
    // The save button is disabled while busy; re-enabled once the save settles.
    await waitFor(() =>
      expect(
        (screen.getByRole("button", { name: /save cv to application/i }) as HTMLButtonElement)
          .disabled,
      ).toBe(false),
    );

    expect(isDirty()).toBe(true);
  });
});
