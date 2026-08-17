// @vitest-environment jsdom
import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { listConnectionModels, updateRouting } from "../api/client";
import type { ConnectionStatus, ModelInfo, Routing } from "../api/types";
import { TASKS, TaskModelsSection } from "./TaskModelsSection";

/** Mirrors DefaultModelSection.test.tsx's boundary choice — mock the API
 * client module directly and render with @testing-library/react + jsdom. */
vi.mock("../api/client", () => ({
  listConnectionModels: vi.fn(),
  testConnectionProvider: vi.fn(),
  updateRouting: vi.fn(),
}));

function makeStatus(overrides: Partial<ConnectionStatus> = {}): ConnectionStatus {
  return {
    provider: "claude",
    label: "Claude",
    modes: ["subscription"],
    subscriptionConnected: true,
    apiKeyConnected: false,
    authMode: "subscription",
    expiresAt: null,
    connectedAt: null,
    ...overrides,
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

const models: ModelInfo[] = [
  { id: "claude-opus-5", label: "Opus 5" },
  { id: "claude-sonnet-5", label: "Sonnet 5" },
];

afterEach(() => {
  cleanup();
  vi.clearAllMocks();
});

describe("TASKS", () => {
  it("pins the five backend task names the picker rows key off of", () => {
    expect(TASKS.map((t) => t.key)).toEqual([
      "truth_extract",
      "keywords",
      "tailor",
      "infer",
      "cover_letter",
    ]);
  });
});

describe("TaskModelsSection", () => {
  it("renders one row per task with its label", () => {
    render(
      <TaskModelsSection
        connections={[makeStatus()]}
        routing={makeRouting()}
        onSaved={vi.fn()}
      />,
    );
    expect(screen.getByText("Truth extraction")).toBeTruthy();
    expect(screen.getByText("Keyword extraction")).toBeTruthy();
    expect(screen.getByText("CV tailoring")).toBeTruthy();
    expect(screen.getByText("Inference detection")).toBeTruthy();
    expect(screen.getByText("Cover letter")).toBeTruthy();
  });

  it("saving the first row calls updateRouting with {tasks: {truth_extract: route}}", async () => {
    vi.mocked(listConnectionModels).mockResolvedValue(models);
    vi.mocked(updateRouting).mockResolvedValueOnce(
      makeRouting({ tasks: { truth_extract: { connection: "claude", model: "claude-opus-5" } } }),
    );
    const onSaved = vi.fn();
    render(
      <TaskModelsSection
        connections={[makeStatus()]}
        routing={makeRouting()}
        onSaved={onSaved}
      />,
    );

    await vi.waitFor(() => {
      expect(listConnectionModels).toHaveBeenCalledWith("claude");
    });

    fireEvent.mouseDown(screen.getAllByLabelText(/^model$/i)[0]);
    fireEvent.click(await screen.findAllByRole("option", { name: "Opus 5" }).then((o) => o[0]));

    fireEvent.click(screen.getAllByRole("button", { name: /^save$/i })[0]);

    await vi.waitFor(() => {
      expect(updateRouting).toHaveBeenCalledWith({
        tasks: { truth_extract: { connection: "claude", model: "claude-opus-5" } },
      });
    });
    expect(onSaved).toHaveBeenCalledWith(
      makeRouting({ tasks: { truth_extract: { connection: "claude", model: "claude-opus-5" } } }),
    );
  });

  it("clearing the second row calls updateRouting with {tasks: {keywords: null}}", async () => {
    vi.mocked(listConnectionModels).mockResolvedValue([]);
    vi.mocked(updateRouting).mockResolvedValueOnce(makeRouting());
    render(
      <TaskModelsSection
        connections={[makeStatus()]}
        routing={makeRouting({
          tasks: { keywords: { connection: "claude", model: "claude-opus-5" } },
        })}
        onSaved={vi.fn()}
      />,
    );

    fireEvent.click(screen.getAllByRole("button", { name: /^clear$/i })[1]);

    await vi.waitFor(() => {
      expect(updateRouting).toHaveBeenCalledWith({ tasks: { keywords: null } });
    });
  });
});
