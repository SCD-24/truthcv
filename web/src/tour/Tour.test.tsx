// @vitest-environment jsdom
/** The coach-mark guided tour overlay. */
import { afterEach, describe, expect, it, vi } from "vitest";
import {
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
} from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { Tour } from "./Tour";
import { TOUR_STEPS } from "./steps";

afterEach(cleanup);

// The real first two steps, so assertions stay tied to what steps.ts declares.
const first = TOUR_STEPS[0];
const second = TOUR_STEPS[1];

describe("Tour", () => {
  it("renders the first step's title", () => {
    render(
      <MemoryRouter>
        <div data-tour={first.anchor} />
        <Tour onDone={() => {}} />
      </MemoryRouter>,
    );
    expect(screen.getByText(first.title)).toBeTruthy();
  });

  it("advances to the second step on Next", async () => {
    render(
      <MemoryRouter>
        <div data-tour={first.anchor} />
        <div data-tour={second.anchor} />
        <Tour onDone={() => {}} />
      </MemoryRouter>,
    );
    fireEvent.click(screen.getByRole("button", { name: /next/i }));
    await waitFor(() => expect(screen.getByText(second.title)).toBeTruthy());
  });

  it("calls onDone immediately when Skip is clicked", () => {
    const onDone = vi.fn();
    render(
      <MemoryRouter>
        <div data-tour={first.anchor} />
        <Tour onDone={onDone} />
      </MemoryRouter>,
    );
    fireEvent.click(screen.getByRole("button", { name: /skip/i }));
    expect(onDone).toHaveBeenCalledTimes(1);
  });

  it("skips a step whose anchor is absent from the DOM", async () => {
    render(
      <MemoryRouter>
        {/* Only the second step's anchor is present; the first must be skipped. */}
        <div data-tour={second.anchor} />
        <Tour onDone={() => {}} />
      </MemoryRouter>,
    );
    await waitFor(() => expect(screen.getByText(second.title)).toBeTruthy());
  });
});
