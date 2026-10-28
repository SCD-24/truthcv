// @vitest-environment jsdom
import { afterEach, describe, expect, it } from "vitest";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { AppLink } from "./AppLink";

const UNSAFE_TARGETS = [
  "/\\evil.com",
  "\\\\evil.com",
  "//evil.com",
  "https://evil.com",
  "javascript:alert(1)",
];

function renderLink(to: string | { pathname: string }) {
  return render(
    <MemoryRouter>
      <AppLink to={to}>go</AppLink>
    </MemoryRouter>,
  );
}

describe("AppLink", () => {
  afterEach(cleanup);

  it.each(UNSAFE_TARGETS)("renders no href for string target %s", (target) => {
    renderLink(target);
    expect(screen.getByText("go")).toBeTruthy();
    expect(document.querySelector("a[href]")).toBeNull();
  });

  it.each(UNSAFE_TARGETS)("renders no href for pathname target %s", (target) => {
    renderLink({ pathname: target });
    expect(screen.getByText("go")).toBeTruthy();
    expect(document.querySelector("a[href]")).toBeNull();
  });

  it("renders no href for a target that is neither string nor pathname", () => {
    render(
      <MemoryRouter>
        <AppLink to={{ search: "?a=1" }}>go</AppLink>
      </MemoryRouter>,
    );
    expect(document.querySelector("a[href]")).toBeNull();
  });

  it("renders and navigates for a same-origin route", () => {
    render(
      <MemoryRouter initialEntries={["/"]}>
        <AppLink to="/next">go</AppLink>
        <Routes>
          <Route path="/" element={<p>home</p>} />
          <Route path="/next" element={<p>arrived</p>} />
        </Routes>
      </MemoryRouter>,
    );
    expect(screen.getByRole("link", { name: "go" }).getAttribute("href")).toBe("/next");
    fireEvent.click(screen.getByRole("link", { name: "go" }));
    expect(screen.getByText("arrived")).toBeTruthy();
  });
});
