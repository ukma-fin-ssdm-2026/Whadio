import { render, screen, within } from "@testing-library/react";
import { userEvent } from "@testing-library/user-event";
import type { ComponentProps } from "react";
import { expect, test, vi } from "vitest";
import { Sidebar } from "./Sidebar";

function renderSidebar(changes: Partial<ComponentProps<typeof Sidebar>> = {}) {
  render(
    <Sidebar
      user={{ name: "Demo Member", email: "member@example.com" }}
      workspaces={[
        { id: "alpha", name: "Alpha", meetingCount: 1 },
        { id: "beta", name: "Beta", meetingCount: 3 },
      ]}
      page="home"
      workspaceId="alpha"
      onHome={() => {}}
      onMeetings={() => {}}
      onWorkspace={() => {}}
      onSignOut={() => {}}
      onNavigate={() => {}}
      {...changes}
    />,
  );
  return within(screen.getByRole("navigation", { name: "Main" }));
}

test("navigation offers Home, Meetings and each workspace with its meeting count", () => {
  // Arrange
  const nav = renderSidebar();

  // Act
  const items = nav.getAllByRole("button").map((item) => item.textContent);

  // Assert
  expect(items).toEqual(["Home", "Meetings", "Alpha1 meeting", "Beta3 meetings"]);
});

test("marks the open workspace as the current page", () => {
  // Arrange
  const nav = renderSidebar({ page: "workspace", workspaceId: "beta" });

  // Act
  const current = nav.getAllByRole("button").filter((item) => item.ariaCurrent === "page");

  // Assert
  expect(current.map((item) => item.textContent)).toEqual(["Beta3 meetings"]);
});

test("marks no item as current on a meeting page", () => {
  // Act
  const nav = renderSidebar({ page: "meeting", workspaceId: "beta" });

  // Assert
  expect(nav.queryByRole("button", { current: true })).not.toBeInTheDocument();
});

test("choosing a workspace opens it", async () => {
  // Arrange
  const onWorkspace = vi.fn();
  const nav = renderSidebar({ onWorkspace });

  // Act
  await userEvent.click(nav.getByRole("button", { name: /^Beta/ }));

  // Assert
  expect(onWorkspace).toHaveBeenCalledExactlyOnceWith("beta");
});

test("choosing an item reports the navigation", async () => {
  // Arrange
  const onNavigate = vi.fn();
  const nav = renderSidebar({ onNavigate });

  // Act
  await userEvent.click(nav.getByRole("button", { name: "Meetings" }));

  // Assert
  expect(onNavigate).toHaveBeenCalledOnce();
});
