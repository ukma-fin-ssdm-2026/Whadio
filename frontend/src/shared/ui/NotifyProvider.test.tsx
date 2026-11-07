import { Dialog } from "@mui/material";
import { render, screen } from "@testing-library/react";
import { expect, test, vi } from "vitest";
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

function NotifyWithAction({ onUndo }: { onUndo: () => void }) {
  const notify = useNotify();
  return (
    <>
      <button
        type="button"
        onClick={() => notify("Deleted", "success", { label: "Undo", onClick: onUndo })}
      >
        Delete
      </button>
      <button type="button">Elsewhere</button>
    </>
  );
}

test("a notification's action runs when chosen", async () => {
  // Arrange
  const onUndo = vi.fn();
  const { user } = renderWithProviders(<NotifyWithAction onUndo={onUndo} />);
  await user.click(screen.getByRole("button", { name: "Delete" }));

  // Act
  await user.click(await screen.findByRole("button", { name: "Undo" }));

  // Assert
  expect(onUndo).toHaveBeenCalledOnce();
});

test("a click elsewhere keeps a notification's action", async () => {
  // Arrange
  const { user } = renderWithProviders(<NotifyWithAction onUndo={() => {}} />);
  await user.click(screen.getByRole("button", { name: "Delete" }));
  await screen.findByRole("button", { name: "Undo" });

  // Act
  await user.click(screen.getByRole("button", { name: "Elsewhere" }));

  // Assert
  expect(screen.getByRole("button", { name: "Undo" })).toBeVisible();
});
