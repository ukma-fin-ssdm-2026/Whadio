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
