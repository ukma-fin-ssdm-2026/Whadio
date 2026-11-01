import { screen } from "@testing-library/react";
import { expect, test } from "vitest";
import { renderAtPath } from "../testing";
import { Breadcrumbs } from "./Breadcrumbs";

test("marks the meeting as the current page after its workspace", async () => {
  // Arrange
  renderAtPath(<Breadcrumbs workspace={{ id: "alpha", name: "Alpha" }} current="Weekly sync" />);

  // Act
  const crumbs = (await screen.findAllByRole("listitem")).map((item) => item.textContent);

  // Assert
  expect(crumbs).toEqual(["Home", "Alpha", "Weekly sync"]);
});

test("links a workspace crumb to its page", async () => {
  // Act
  renderAtPath(<Breadcrumbs workspace={{ id: "alpha", name: "Alpha" }} current="Weekly sync" />);

  // Assert
  expect(await screen.findByRole("link", { name: "Alpha" })).toHaveAttribute(
    "href",
    "/workspaces/alpha",
  );
});

test("marks the last crumb as the current page", async () => {
  // Act
  renderAtPath(<Breadcrumbs current="Meetings" />);

  // Assert
  expect(await screen.findByText("Meetings")).toHaveAttribute("aria-current", "page");
});
