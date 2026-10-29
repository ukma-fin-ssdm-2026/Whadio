import { screen } from "@testing-library/react";
import { expect, test, vi } from "vitest";
import { renderWithProviders } from "../testing/render";
import { CopyField } from "./CopyField";

const renderField = () =>
  renderWithProviders(
    <CopyField value="whadio_secret" label="MCP key secret" copyLabel="Copy key" />,
  );

test("shows the value read-only", () => {
  // Act
  renderField();

  // Assert
  expect(screen.getByLabelText("MCP key secret")).toHaveAttribute("readonly");
});

test("copy puts the value on the clipboard", async () => {
  // Arrange
  const { user } = renderField();

  // Act
  await user.click(screen.getByRole("button", { name: "Copy key" }));

  // Assert
  expect(await navigator.clipboard.readText()).toBe("whadio_secret");
});

test("copy confirms with a Copied notification", async () => {
  // Arrange
  const { user } = renderField();

  // Act
  await user.click(screen.getByRole("button", { name: "Copy key" }));

  // Assert
  expect(await screen.findByRole("alert")).toHaveTextContent("Copied");
});

test("a refused clipboard asks to copy by hand", async () => {
  // Arrange
  const { user } = renderField();
  vi.spyOn(navigator.clipboard, "writeText").mockRejectedValue(new DOMException("Denied"));

  // Act
  await user.click(screen.getByRole("button", { name: "Copy key" }));

  // Assert
  expect(await screen.findByRole("alert")).toHaveTextContent("Could not copy");
});
