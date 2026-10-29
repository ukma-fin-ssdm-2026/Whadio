import { Dialog } from "@mui/material";
import { render, screen } from "@testing-library/react";
import { expect, test } from "vitest";
import { renderWithProviders } from "../testing/render";
import { useNotify } from "./NotifyProvider";

function NotifyButtons() {
  const notify = useNotify();
  return (
    <>
      <button type="button" onClick={() => notify("Key copied")}>
        First
      </button>
      <button type="button" onClick={() => notify("Could not copy", "error")}>
        Second
      </button>
    </>
  );
}

test("shows the notification in an alert", async () => {
  // Arrange
  const { user } = renderWithProviders(<NotifyButtons />);

  // Act
  await user.click(screen.getByRole("button", { name: "First" }));

  // Assert
  expect(await screen.findByRole("alert")).toHaveTextContent("Key copied");
});

test("a later notification replaces the earlier one", async () => {
  // Arrange
  const { user } = renderWithProviders(<NotifyButtons />);
  await user.click(screen.getByRole("button", { name: "First" }));

  // Act
  await user.click(screen.getByRole("button", { name: "Second" }));

  // Assert
  expect(await screen.findAllByRole("alert")).toEqual([
    expect.objectContaining({ textContent: "Could not copy" }),
  ]);
});

test("a notification raised from an open dialog stays accessible", async () => {
  // Arrange
  const { user } = renderWithProviders(
    <Dialog open>
      <NotifyButtons />
    </Dialog>,
  );

  // Act
  await user.click(screen.getByRole("button", { name: "First" }));

  // Assert
  expect(await screen.findByRole("alert")).toHaveTextContent("Key copied");
});

test("useNotify outside a NotifyProvider throws", () => {
  // Act
  const rendering = () => render(<NotifyButtons />);

  // Assert
  expect(rendering).toThrow("NotifyProvider");
});
