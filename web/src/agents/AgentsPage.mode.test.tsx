// @vitest-environment jsdom
/** The autonomy slider: off / semi-auto. Full auto is no longer selectable —
 * its per-run application cap is unenforced on roles the agent finds itself —
 * but a config already stored as `full` still gets its mark. Stubbing follows
 * AgentsPage.model.test.tsx — mock the API client module, render with jsdom. */
import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import {
  getAgentConfig,
  getAgentStatus,
  getProfileAnswers,
  getRouting,
  listConnectionModels,
  listConnections,
  updateAgentConfig,
} from "../api/client";
import type { AgentConfig, AgentStatus, Routing } from "../api/types";
import type { ProfileAnswers } from "../api/types";
import { AgentsPage } from "./AgentsPage";

vi.mock("../api/client", () => ({
  getAgentConfig: vi.fn(),
  getAgentStatus: vi.fn(),
  getProfileAnswers: vi.fn(),
  getRouting: vi.fn(),
  listConnections: vi.fn(),
  listConnectionModels: vi.fn(),
  listRuns: vi.fn().mockResolvedValue([]),
  triggerAgentRun: vi.fn(),
  updateAgentConfig: vi.fn(),
  saveProfileAnswers: vi.fn(),
  updateRouting: vi.fn(),
  getSigninQueue: vi.fn().mockResolvedValue({ sites: [] }),
}));

function makeConfig(overrides: Partial<AgentConfig> = {}): AgentConfig {
  return {
    mode: "full",
    enabled: true,
    blockedCompanies: [],
    runAt: ["09:00"],
    runDays: ["mon"],
    profiles: [],
    jobBoards: [],
    targetCompanies: [],
    cooldownDays: null,
    cooldownDaysSameRole: null,
    cooldownDaysSameCompany: null,
    maxApplicationsPerRun: null,
    maxPostingAgeDays: null,
    companyBoards: [],
    ...overrides,
  };
}

/** Copied verbatim from AgentsPage.model.test.tsx — long, unchanged, and
 * already correct. */
function makeAnswers(): ProfileAnswers {
  return {
    phone: "",
    workAuthorisation: "",
    noticePeriod: "",
    locationPreference: "",
    canonicalCvAssetId: null,
    name: "",
    email: "",
    linkedin: "",
    github: "",
    website: "",
    workAuthorisationNote: "",
  requiresSponsorship: "",
    authorizedNonGermanCountry: "",
    languages: "",
    highestRelevantDegree: "",
    otherDegree: "",
    csDegree: "",
    gpa: "",
    gender: "",
    yearsOfExperience: "",
    currentRole: "",
    howDidYouHear: "",
  };
}

function makeRouting(overrides: Partial<Routing> = {}): Routing {
  return {
    tasks: {},
    agent: null,
    default: null,
    ...overrides,
  };
}

function makeAgentStatus(overrides: Partial<AgentStatus> = {}): AgentStatus {
  return {
    running: false,
    cancelling: false,
    lastStartedAt: null,
    lastFinishedAt: null,
    lastExitCode: null,
    lastCancelled: false,
    ...overrides,
  };
}

async function renderWithMode(mode: AgentConfig["mode"]) {
  vi.mocked(getAgentConfig).mockResolvedValue(makeConfig({ mode, enabled: mode !== "off" }));
  vi.mocked(getAgentStatus).mockResolvedValue(makeAgentStatus());
  vi.mocked(getProfileAnswers).mockResolvedValue(makeAnswers());
  vi.mocked(getRouting).mockResolvedValue(makeRouting());
  vi.mocked(listConnections).mockResolvedValue({ connections: [] } as never);
  vi.mocked(listConnectionModels).mockResolvedValue([]);
  render(
    <MemoryRouter>
      <AgentsPage onBack={vi.fn()} />
    </MemoryRouter>,
  );
  await screen.findByRole("slider", { name: "Agent autonomy" });
}

/** Fires the hidden range input's native `change` event, then the commit
 * event a keyboard interaction produces synchronously in the same handler
 * (MUI's `useSlider` calls `onChange` then `onChangeCommitted` back-to-back
 * for input-driven changes) — mirroring what a keyboard-only operator does. */
function moveSliderTo(value: number) {
  const slider = screen.getByRole("slider", { name: "Agent autonomy" });
  fireEvent.change(slider, { target: { value: String(value) } });
}

// jsdom implements neither method; MUI's Slider calls both unconditionally
// during pointer-drag handling (setPointerCapture is wrapped in a try/catch
// there, but hasPointerCapture is not), so a bare drag simulation throws
// without this polyfill. Real browsers implement both — `typeof` rather than
// `in` because TS's lib.dom already types these as always present on
// Element, which narrows an `in`-guarded negative branch to `never`.
if (typeof Element.prototype.hasPointerCapture !== "function") {
  Element.prototype.hasPointerCapture = () => false;
}
if (typeof Element.prototype.setPointerCapture !== "function") {
  Element.prototype.setPointerCapture = () => {};
}
if (typeof Element.prototype.releasePointerCapture !== "function") {
  Element.prototype.releasePointerCapture = () => {};
}

/** Simulates a pointer drag across the slider's marks: press at `fromValue`,
 * move through every value up to and including `toValue`, then release.
 * MUI only fires `onChangeCommitted` on release, so this is what pins down
 * that a drag crossing an intermediate mark issues a single PUT. */
function dragSliderAcross(fromValue: number, toValue: number) {
  const slider = screen.getByRole("slider", { name: "Agent autonomy" });
  const root = slider.closest(".MuiSlider-root") as HTMLElement;
  const width = 360; // matches sx={{ maxWidth: 360 }} on the Slider — arbitrary otherwise
  vi.spyOn(root, "getBoundingClientRect").mockReturnValue({
    left: 0,
    right: width,
    width,
    top: 0,
    bottom: 4,
    height: 4,
    x: 0,
    y: 0,
    toJSON: () => {},
  } as DOMRect);

  const xFor = (v: number) => (v / 2) * width; // min=0, max=2
  const pointerId = 1;

  fireEvent.pointerDown(root, {
    pointerId,
    button: 0,
    clientX: xFor(fromValue),
    clientY: 2,
  });

  const step = toValue >= fromValue ? 1 : -1;
  for (let v = fromValue; v !== toValue; v += step) {
    const next = v + step;
    fireEvent.pointerMove(document, {
      pointerId,
      buttons: 1,
      clientX: xFor(next),
      clientY: 2,
    });
  }

  fireEvent.pointerUp(document, { pointerId, clientX: xFor(toValue), clientY: 2 });
}

afterEach(() => {
  cleanup();
  vi.clearAllMocks();
});

describe("AgentsPage autonomy slider", () => {
  it("sits at the stored mode and explains it", async () => {
    await renderWithMode("semi");
    expect(screen.getByRole("slider", { name: "Agent autonomy" }).getAttribute("value")).toBe("1");
    expect(screen.getByText(/You draft the cover letter and approve/)).toBeTruthy();
  });

  it("moving it writes the new mode", async () => {
    await renderWithMode("semi");
    vi.mocked(updateAgentConfig).mockResolvedValue(makeConfig({ mode: "off", enabled: false }));
    moveSliderTo(0);
    await waitFor(() => expect(updateAgentConfig).toHaveBeenCalledWith({ mode: "off" }));
  });

  it("offers only off and semi-auto — full auto cannot be chosen", async () => {
    await renderWithMode("semi");
    const slider = screen.getByRole("slider", { name: "Agent autonomy" });
    expect(slider.getAttribute("max")).toBe("1");
    expect(screen.queryByText("Full auto")).toBeNull();
  });

  it("keeps the full-auto mark for a config already stored that way", async () => {
    // Dropping it would rest the thumb on "Off" while the agent applied on its
    // own, which is the one state this control must never misreport.
    await renderWithMode("full");
    const slider = screen.getByRole("slider", { name: "Agent autonomy" });
    expect(slider.getAttribute("value")).toBe("2");
    expect(screen.getByText("Full auto")).toBeTruthy();
    expect(screen.getByText(/Not offered here for now/)).toBeTruthy();
  });

  it("leaving full auto is a one-way door", async () => {
    await renderWithMode("full");
    vi.mocked(updateAgentConfig).mockResolvedValue(makeConfig({ mode: "semi" }));
    moveSliderTo(1);
    await waitFor(() => expect(updateAgentConfig).toHaveBeenCalledWith({ mode: "semi" }));
    await waitFor(() =>
      expect(screen.getByRole("slider", { name: "Agent autonomy" }).getAttribute("max")).toBe("1"),
    );
    expect(screen.queryByText("Full auto")).toBeNull();
  });

  it("off is reachable and explains that nothing is submitted", async () => {
    await renderWithMode("full");
    vi.mocked(updateAgentConfig).mockResolvedValue(makeConfig({ mode: "off", enabled: false }));
    moveSliderTo(0);
    await waitFor(() => expect(updateAgentConfig).toHaveBeenCalledWith({ mode: "off" }));
    expect(await screen.findByText(/Nothing is submitted/)).toBeTruthy();
  });

  it("reverts to the previous mode when the save fails", async () => {
    await renderWithMode("semi");
    vi.mocked(updateAgentConfig).mockRejectedValue(new Error("nope"));
    moveSliderTo(0);
    expect(await screen.findByText("nope")).toBeTruthy();
    await waitFor(() =>
      expect(screen.getByRole("slider", { name: "Agent autonomy" }).getAttribute("value")).toBe("1"),
    );
  });

  it("dragging past an intermediate mark commits only once, at the final value", async () => {
    await renderWithMode("full");
    vi.mocked(updateAgentConfig).mockResolvedValue(makeConfig({ mode: "off", enabled: false }));

    // Drag from full auto (2) through semi-auto (1) to off (0) in one motion.
    dragSliderAcross(2, 0);

    await waitFor(() => expect(updateAgentConfig).toHaveBeenCalledTimes(1));
    expect(updateAgentConfig).toHaveBeenCalledWith({ mode: "off" });
  });

  it("the thumb tracks a drag before release without issuing a PUT", async () => {
    await renderWithMode("full");
    vi.mocked(updateAgentConfig).mockResolvedValue(makeConfig({ mode: "semi" }));
    const slider = screen.getByRole("slider", { name: "Agent autonomy" });
    const root = slider.closest(".MuiSlider-root") as HTMLElement;
    const width = 360;
    vi.spyOn(root, "getBoundingClientRect").mockReturnValue({
      left: 0,
      right: width,
      width,
      top: 0,
      bottom: 4,
      height: 4,
      x: 0,
      y: 0,
      toJSON: () => {},
    } as DOMRect);

    fireEvent.pointerDown(root, { pointerId: 1, button: 0, clientX: width, clientY: 2 });
    fireEvent.pointerMove(document, { pointerId: 1, buttons: 1, clientX: width / 2, clientY: 2 });

    expect(slider.getAttribute("value")).toBe("1");
    expect(updateAgentConfig).not.toHaveBeenCalled();

    fireEvent.pointerUp(document, { pointerId: 1, clientX: width / 2, clientY: 2 });
    await waitFor(() => expect(updateAgentConfig).toHaveBeenCalledWith({ mode: "semi" }));
  });
});
