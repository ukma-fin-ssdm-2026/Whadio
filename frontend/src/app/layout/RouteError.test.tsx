import { render, screen } from "@testing-library/react";
import { expect, test } from "vitest";
import { ApiError } from "@/shared/api/errors";
import { RouteError } from "./RouteError";

test("repeats what the server said", () => {
  // Arrange
  const error = new ApiError({ status: 503, code: "INTERNAL_ERROR", message: "Down for repairs" });

  // Act
  render(<RouteError error={error} />);

  // Assert
  expect(screen.getByRole("alert")).toHaveTextContent("Down for repairs");
});

test("names no code-level detail of a chunk that failed to load", () => {
  // Arrange
  const error = new TypeError("Failed to fetch dynamically imported module: /assets/x.js");

  // Act
  render(<RouteError error={error} />);

  // Assert
  expect(screen.getByRole("alert")).toHaveTextContent("This page could not be loaded.");
});
