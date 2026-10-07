// @vitest-environment jsdom
import { describe, it, expect, vi, afterEach } from "vitest";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { RunSourceUrls } from "./RunSourceUrls";
import * as client from "../api/client";
import type { BoardBreakdown, RunUrlEntry } from "../api/types";

const ROW: BoardBreakdown = {
  board: "lever.co", channel: "direct", postingsSeen: 6, previouslyScreened: 2, notAPosting: 0,
  duplicate: 0, failed: 1, forReview: 3, rejected: 0, blocked: 0,
};

function entry(url: string, detail = ""): RunUrlEntry {
  return { url, outcome: "failed", detail, sources: [{ source: "lever.co", channel: "direct" }] };
}

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});

describe("RunSourceUrls", () => {
  it("fetches non-zero sections lazily, leaving previously screened collapsed", async () => {
    const spy = vi.spyOn(client, "getRunUrls").mockImplementation(async (_id, p) => ({
      entries: [entry(`https://x.test/${p.outcome}`, "boom")],
      total: 1,
    }));
    render(<RunSourceUrls runId="r1" row={ROW} truncated={false} />);

    await waitFor(() => expect(screen.getByText("https://x.test/failed")).toBeTruthy());
    expect(spy).toHaveBeenCalledWith("r1", { source: "lever.co", channel: "direct", outcome: "failed", limit: 50, offset: 0 });
    expect(spy).toHaveBeenCalledWith("r1", { source: "lever.co", channel: "direct", outcome: "for_review", limit: 50, offset: 0 });
    expect(spy).toHaveBeenCalledTimes(2);

    const link = screen.getByRole("link", { name: "https://x.test/failed" });
    expect(link.getAttribute("target")).toBe("_blank");
    expect(link.getAttribute("rel")).toBe("noopener noreferrer");
    expect(screen.getAllByText(/boom/).length).toBeGreaterThan(0);
    expect(screen.getByRole("link", { name: "Open approvals" }).getAttribute("href")).toBe("/approvals");

    fireEvent.click(screen.getByRole("button", { name: /Previously screened/ }));
    await waitFor(() => expect(spy).toHaveBeenCalledTimes(3));
  });

  it("shows more and offers retry on error", async () => {
    const spy = vi
      .spyOn(client, "getRunUrls")
      .mockResolvedValueOnce({ entries: [entry("https://a.test/1")], total: 2 })
      .mockRejectedValueOnce(new Error("nope"))
      .mockResolvedValue({ entries: [entry("https://a.test/2")], total: 2 });
    render(<RunSourceUrls runId="r1" row={{ ...ROW, forReview: 0, previouslyScreened: 0 }} truncated />);

    await waitFor(() => expect(screen.getByText("https://a.test/1")).toBeTruthy());
    expect(screen.getByText("Only the first 1,000 links of this run were kept")).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "Show more" }));
    await waitFor(() => expect(screen.getByRole("alert").textContent).toContain("nope"));
    fireEvent.click(screen.getByRole("button", { name: "Retry" }));
    await waitFor(() => expect(screen.getByText("https://a.test/2")).toBeTruthy());
    expect(spy).toHaveBeenLastCalledWith("r1", { source: "lever.co", channel: "direct", outcome: "failed", limit: 50, offset: 1 });
  });
});
