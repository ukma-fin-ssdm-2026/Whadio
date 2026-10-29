import { render, screen } from "@testing-library/react";
import { expect, test } from "vitest";
import { EmptyState } from "./EmptyState";

test("shows the title with its hint", () => {
  // Act
  const { container } = render(<EmptyState title="No meetings found" hint="Try another filter." />);

  // Assert
  expect(container).toHaveTextContent(/^No meetings foundTry another filter\.$/);
});

test("renders the action", () => {
  // Act
  render(<EmptyState title="No keys" action={<button type="button">Create key</button>} />);

  // Assert
  expect(screen.getByRole("button", { name: "Create key" })).toBeInTheDocument();
});
