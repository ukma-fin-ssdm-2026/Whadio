import { screen, within } from "@testing-library/react";
import { expect, test } from "vitest";
import type { Schemas } from "@/shared/api/types";
import { formatDate } from "@/shared/lib/format";
import { errorBody, memberRead, page } from "@/shared/testing/fixtures";
import { renderWithProviders } from "@/shared/testing/render";
import { http, server } from "@/shared/testing/server";
import { MemberPanel } from "./MemberPanel";

const OWNER = memberRead({
  user_id: "owner",
  name: "Demo Owner",
  email: "owner@example.test",
  role: "owner",
  joined_at: "2026-10-01T09:00:00Z",
});
const MEMBER = memberRead();

type MemberPage = ReturnType<typeof page<Schemas["MemberRead"]>>;

function serveMembers(answer: (cursor: string | null) => MemberPage) {
  const searches: string[] = [];
  server.use(
    http.get("/api/v1/workspaces/{workspace_id}/members", ({ request, response }) => {
      const url = new URL(request.url);
      searches.push(url.search);
      return response(200).json(answer(url.searchParams.get("cursor")));
    }),
  );
  return searches;
}

const twoPages = (cursor: string | null) => (cursor ? page([MEMBER]) : page([OWNER], "next-page"));

const renderPanel = () => renderWithProviders(<MemberPanel workspaceId="workspace" />);

const listedRows = async () =>
  within(await screen.findByRole("list", { name: "Workspace members" })).getAllByRole("listitem");

const rowParts = (row: HTMLElement) =>
  [".MuiListItemText-primary", ".MuiListItemText-secondary", ".MuiChip-label"].map(
    (part) => row.querySelector(part)?.textContent,
  );

async function loadSecondPage() {
  const { user } = renderPanel();
  await user.click(await screen.findByRole("button", { name: "Load more members" }));
  await screen.findByText(MEMBER.name);
}

test("lists each member's name, email, joining date and role", async () => {
  // Arrange
  serveMembers(() => page([OWNER, MEMBER]));

  // Act
  renderPanel();

  // Assert
  expect((await listedRows()).map(rowParts)).toEqual([
    [OWNER.name, `${OWNER.email} · Joined ${formatDate(OWNER.joined_at)}`, "Owner"],
    [MEMBER.name, `${MEMBER.email} · Joined ${formatDate(MEMBER.joined_at)}`, "Member"],
  ]);
});

test("Load more members asks for the page after the cursor", async () => {
  // Arrange
  const searches = serveMembers(twoPages);

  // Act
  await loadSecondPage();

  // Assert
  expect(searches).toEqual(["?limit=100", "?limit=100&cursor=next-page"]);
});

test("Load more members appends the next page", async () => {
  // Arrange
  serveMembers(twoPages);

  // Act
  await loadSecondPage();

  // Assert
  expect((await listedRows()).map((row) => rowParts(row)[0])).toEqual([OWNER.name, MEMBER.name]);
});

test("a failed load shows the server's message", async () => {
  // Arrange
  server.use(
    http.get("/api/v1/workspaces/{workspace_id}/members", ({ response }) =>
      response(404).json(errorBody("NOT_FOUND", "Workspace not found")),
    ),
  );

  // Act
  renderPanel();

  // Assert
  expect(await screen.findByRole("alert")).toHaveTextContent("Workspace not found");
});
