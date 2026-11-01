import { render, screen } from "@testing-library/react";
import { expect, test } from "vitest";
import { ErrorBanner } from "./ErrorBanner";

test("the banner announces its message as an alert", () => {
  // Arrange
  const message = "The meeting could not be loaded.";

  // Act
  render(<ErrorBanner>{message}</ErrorBanner>);

  // Assert
  expect(screen.getByRole("alert")).toHaveTextContent(message);
});
