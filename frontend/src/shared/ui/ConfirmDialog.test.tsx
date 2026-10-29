import { render, screen } from "@testing-library/react";
import { userEvent } from "@testing-library/user-event";
import { expect, test, vi } from "vitest";
import { ConfirmDialog } from "./ConfirmDialog";

function renderDialog({ pending = false } = {}) {
  const onConfirm = vi.fn();
  const onCancel = vi.fn();
  render(
    <ConfirmDialog
      open
      title="Revoke this key?"
      confirmLabel="Revoke"
      destructive
      pending={pending}
      onConfirm={onConfirm}
      onCancel={onCancel}
    >
      Assistants using it lose access.
    </ConfirmDialog>,
  );
  return { onConfirm, onCancel, user: userEvent.setup() };
}

test("names the dialog by its title", () => {
  // Act
  renderDialog();

  // Assert
  expect(screen.getByRole("dialog", { name: "Revoke this key?" })).toBeInTheDocument();
});

test("confirming calls onConfirm", async () => {
  // Arrange
  const { onConfirm, user } = renderDialog();

  // Act
  await user.click(screen.getByRole("button", { name: "Revoke" }));

  // Assert
  expect(onConfirm).toHaveBeenCalledOnce();
});

test("cancelling calls onCancel", async () => {
  // Arrange
  const { onCancel, user } = renderDialog();

  // Act
  await user.click(screen.getByRole("button", { name: "Cancel" }));

  // Assert
  expect(onCancel).toHaveBeenCalledOnce();
});

test("Escape cancels", async () => {
  // Arrange
  const { onCancel, user } = renderDialog();

  // Act
  await user.keyboard("{Escape}");

  // Assert
  expect(onCancel).toHaveBeenCalledOnce();
});

test("Escape does not cancel while the action is pending", async () => {
  // Arrange
  const { onCancel, user } = renderDialog({ pending: true });

  // Act
  await user.keyboard("{Escape}");

  // Assert
  expect(onCancel).not.toHaveBeenCalled();
});

test("cancel is disabled while the action is pending", () => {
  // Act
  renderDialog({ pending: true });

  // Assert
  expect(screen.getByRole("button", { name: "Cancel" })).toBeDisabled();
});
