import { render, screen } from "@testing-library/react";
import { userEvent } from "@testing-library/user-event";
import { expect, test } from "vitest";
import { WorkspaceSettings } from "./WorkspaceSettings";

const workspace = { id: "alpha", name: "Alpha", provider: "Whadio", preset: "summary" };

function renderSettings() {
  render(<WorkspaceSettings workspace={workspace} assistantSettings={<p>Assistant keys</p>} />);
}

test("opens on the workspace section", () => {
  // Act
  renderSettings();

  // Assert
  expect(screen.getByRole("heading", { level: 2 })).toHaveTextContent(/^Workspace settings$/);
});

test("choosing AI assistant shows the assistant settings", async () => {
  // Arrange
  renderSettings();

  // Act
  await userEvent.click(screen.getByRole("button", { name: "AI assistant" }));

  // Assert
  expect(screen.getByText("Assistant keys")).toBeInTheDocument();
});

test("choosing AI assistant hides the workspace settings", async () => {
  // Arrange
  renderSettings();

  // Act
  await userEvent.click(screen.getByRole("button", { name: "AI assistant" }));

  // Assert
  expect(screen.queryByText("Notes provider")).not.toBeInTheDocument();
});

test("marks the chosen section as current", async () => {
  // Arrange
  renderSettings();

  // Act
  await userEvent.click(screen.getByRole("button", { name: "AI assistant" }));

  // Assert
  expect(screen.getByRole("button", { current: true })).toHaveTextContent(/^AI assistant$/);
});
