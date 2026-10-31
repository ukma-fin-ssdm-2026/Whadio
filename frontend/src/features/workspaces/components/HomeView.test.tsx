import { render, screen } from "@testing-library/react";
import { userEvent } from "@testing-library/user-event";
import { expect, test, vi } from "vitest";
import { HomeView } from "./HomeView";

const WORKSPACE = { id: "alpha", name: "Alpha", role: "Owner", members: 1 };

function renderHome(members = 1, onWorkspace = () => {}) {
  render(
    <HomeView
      workspaces={[{ ...WORKSPACE, members }]}
      renderMeetingFigures={(id) => `figures of ${id}`}
      onWorkspace={onWorkspace}
    />,
  );
}

test("a lone member is singular", () => {
  // Act
  renderHome();

  // Assert
  expect(screen.getByText(/1 member ·/)).toBeInTheDocument();
});

test("several members are plural", () => {
  // Act
  renderHome(3);

  // Assert
  expect(screen.getByText(/3 members ·/)).toBeInTheDocument();
});

test("a row shows the figures the app supplies for its workspace", () => {
  // Act
  renderHome();

  // Assert
  expect(screen.getByText(/figures of alpha/)).toBeInTheDocument();
});

test("choosing a row opens its workspace", async () => {
  // Arrange
  const onWorkspace = vi.fn();
  renderHome(1, onWorkspace);

  // Act
  await userEvent.click(screen.getByRole("button", { name: /Alpha/ }));

  // Assert
  expect(onWorkspace).toHaveBeenCalledExactlyOnceWith("alpha");
});
