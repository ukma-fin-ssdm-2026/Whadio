import { screen, within } from "@testing-library/react";
import { userEvent } from "@testing-library/user-event";
import type { ComponentProps } from "react";
import { expect, test, vi } from "vitest";
import { renderAtPath } from "../testing";
import { Sidebar } from "./Sidebar";

async function renderSidebar(path = "/", changes: Partial<ComponentProps<typeof Sidebar>> = {}) {
  const router = renderAtPath(
    <Sidebar
      user={{ name: "Demo Member", email: "member@example.com" }}
      workspaces={[
        { id: "alpha", name: "Alpha" },
        { id: "beta", name: "Beta" },
      ]}
      signOutAction={null}
      onNavigate={() => {}}
      {...changes}
    />,
    path,
  );
  const nav = await screen.findByRole("navigation", { name: "Main" });
  return { nav: within(nav), router };
}

const currentItems = (links: HTMLElement[]) =>
  links.filter((item) => item.ariaCurrent === "page").map((item) => item.textContent);

test("navigation offers Home, Meetings and each workspace", async () => {
  // Arrange
  const { nav } = await renderSidebar();

  // Act
  const items = nav.getAllByRole("link").map((item) => item.textContent);

  // Assert
  expect(items).toEqual(["Home", "Meetings", "Alpha", "Beta"]);
});

test.for([
  ["Home", "/"],
  ["Meetings", "/meetings"],
  ["Beta", "/workspaces/beta"],
  ["Beta", "/workspaces/beta/settings"],
] as const)("marks %s as the current page at %s", async ([label, path]) => {
  // Act
  const { nav } = await renderSidebar(path);

  // Assert
  expect(currentItems(nav.getAllByRole("link"))).toEqual([label]);
});

test("selects the current item", async () => {
  // Act
  const { nav } = await renderSidebar("/workspaces/beta");

  // Assert
  expect(nav.getByRole("link", { name: "Beta" })).toHaveClass("Mui-selected");
});

test("a workspace entry shows its name without a meeting count", async () => {
  // Arrange
  const { nav } = await renderSidebar();

  // Act
  const entry = nav.getByRole("link", { name: /^Beta/ });

  // Assert
  expect(entry).toHaveTextContent(/^Beta$/);
});

test("marks no item as current on a meeting page", async () => {
  // Act
  const { nav } = await renderSidebar("/meetings/meeting");

  // Assert
  expect(currentItems(nav.getAllByRole("link"))).toEqual([]);
});

test("choosing a workspace opens it", async () => {
  // Arrange
  const { nav } = await renderSidebar();

  // Act & Assert
  expect(nav.getByRole("link", { name: /^Beta/ })).toHaveAttribute("href", "/workspaces/beta");
});

test("choosing an item reports the navigation", async () => {
  // Arrange
  const onNavigate = vi.fn();
  const { nav } = await renderSidebar("/", { onNavigate });

  // Act
  await userEvent.click(nav.getByRole("link", { name: "Meetings" }));

  // Assert
  expect(onNavigate).toHaveBeenCalledOnce();
});
