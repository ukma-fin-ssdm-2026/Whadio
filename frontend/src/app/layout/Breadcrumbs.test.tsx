import { render, screen } from "@testing-library/react";
import { expect, test } from "vitest";
import { Breadcrumbs } from "./Breadcrumbs";

test("marks the meeting as the current page after its workspace", () => {
  // Arrange
  render(
    <Breadcrumbs
      page="meeting"
      workspace={{ id: "alpha", name: "Alpha" }}
      meeting={{ title: "Weekly sync" }}
      onHome={() => {}}
      onWorkspace={() => {}}
    />,
  );

  // Act
  const crumbs = screen.getAllByRole("listitem").map((item) => item.textContent);

  // Assert
  expect(crumbs).toEqual(["Home", "Alpha", "Weekly sync"]);
});

test("marks the last crumb as the current page", () => {
  // Act
  render(
    <Breadcrumbs
      page="meetings"
      workspace={undefined}
      meeting={undefined}
      onHome={() => {}}
      onWorkspace={() => {}}
    />,
  );

  // Assert
  expect(screen.getByText("Meetings")).toHaveAttribute("aria-current", "page");
});

test.each([
  { page: "meeting", fallback: "Meeting" },
  { page: "workspace", fallback: "Workspace" },
] as const)("names the current crumb $fallback when its $page is missing", ({ page, fallback }) => {
  // Act
  render(
    <Breadcrumbs
      page={page}
      workspace={undefined}
      meeting={undefined}
      onHome={() => {}}
      onWorkspace={() => {}}
    />,
  );

  // Assert
  expect(screen.getByText(fallback)).toHaveAttribute("aria-current", "page");
});
