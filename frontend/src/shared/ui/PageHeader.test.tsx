import { render, screen } from "@testing-library/react";
import { expect, test } from "vitest";
import { PageHeader } from "./PageHeader";

test("renders the title as the page's only first-level heading", () => {
  // Act
  render(<PageHeader title="Meetings" overline="Owner workspace" />);

  // Assert
  expect(screen.getAllByRole("heading", { level: 1 }).map((h) => h.textContent)).toEqual([
    "Meetings",
  ]);
});

test("shows the overline above the title", () => {
  // Arrange
  render(<PageHeader title="Meetings" overline="Owner workspace" />);

  // Act
  const overline = screen.getByText("Owner workspace");

  // Assert
  expect(overline.compareDocumentPosition(screen.getByRole("heading"))).toBe(
    Node.DOCUMENT_POSITION_FOLLOWING,
  );
});

test("renders the actions", () => {
  // Act
  render(<PageHeader title="Meetings" actions={<button type="button">Settings</button>} />);

  // Assert
  expect(screen.getByRole("button", { name: "Settings" })).toBeInTheDocument();
});
