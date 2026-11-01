import { render, screen, waitFor } from "@testing-library/react";
import { userEvent } from "@testing-library/user-event";
import { afterEach, expect, test, vi } from "vitest";
import { stubViewportWidth } from "../testing";
import { AppShell } from "./AppShell";

function renderShell(width: number) {
  stubViewportWidth(width);
  render(
    <AppShell
      renderSidebar={(onNavigate) => (
        <button type="button" onClick={onNavigate}>
          Meetings
        </button>
      )}
    >
      Page content
    </AppShell>,
  );
}

async function openDrawer() {
  renderShell(390);
  await userEvent.click(screen.getByRole("button", { name: "Open navigation" }));
}

afterEach(() => {
  vi.unstubAllGlobals();
});

test("small viewport hides the navigation until the menu button is pressed", () => {
  // Act
  renderShell(390);

  // Assert
  expect(screen.queryByRole("button", { name: "Meetings" })).not.toBeInTheDocument();
});

test("small viewport opens the navigation from the menu button", async () => {
  // Act
  await openDrawer();

  // Assert
  expect(screen.getByRole("button", { name: "Meetings" })).toBeVisible();
});

test("small viewport closes the navigation after navigating", async () => {
  // Arrange
  await openDrawer();

  // Act
  await userEvent.click(screen.getByRole("button", { name: "Meetings" }));

  // Assert
  await waitFor(() => expect(screen.queryByRole("button", { name: "Meetings" })).toBeNull());
});

test("small viewport closes the navigation on Escape", async () => {
  // Arrange
  await openDrawer();

  // Act
  await userEvent.keyboard("{Escape}");

  // Assert
  await waitFor(() => expect(screen.queryByRole("button", { name: "Meetings" })).toBeNull());
});

test("wide viewport shows the navigation without a menu button", () => {
  // Act
  renderShell(1440);

  // Assert
  expect(screen.queryByRole("button", { name: "Open navigation" })).not.toBeInTheDocument();
});

test("wide viewport keeps the navigation open", () => {
  // Act
  renderShell(1440);

  // Assert
  expect(screen.getByRole("button", { name: "Meetings" })).toBeVisible();
});

test("renders the page inside the main landmark", () => {
  // Act
  renderShell(1440);

  // Assert
  expect(screen.getByRole("main")).toHaveTextContent("Page content");
});
