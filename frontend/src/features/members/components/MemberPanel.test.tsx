import { screen, waitFor, within } from "@testing-library/react";
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
const MODERATOR = memberRead({
  user_id: "moderator",
  name: "Demo Moderator",
  email: "moderator@example.test",
  role: "moderator",
});
const MEMBER = memberRead();
const SELF = { owner: OWNER, moderator: MODERATOR, member: MEMBER };
const MANAGERS = ["owner", "moderator"] as const;

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

function serveTeam() {
  let members = [OWNER, MODERATOR, MEMBER];
  const changes: object[] = [];
  serveMembers(() => page(members));
  server.use(
    http.patch(
      "/api/v1/workspaces/{workspace_id}/members/{user_id}",
      async ({ params, request, response }) => {
        const body = await request.json();
        changes.push({ user: params.user_id, body });
        members = members.map((item) =>
          item.user_id === params.user_id ? { ...item, ...body } : item,
        );
        return response(200).json(memberRead({ user_id: params.user_id, ...body }));
      },
    ),
  );
  return changes;
}

const twoPages = (cursor: string | null) => (cursor ? page([MEMBER]) : page([OWNER], "next-page"));

const renderPanel = (myRole: Schemas["Role"] = "member") =>
  renderWithProviders(
    <MemberPanel workspaceId="workspace" myRole={myRole} currentUserId={SELF[myRole].user_id} />,
  );

const listedRows = async () =>
  within(await screen.findByRole("list", { name: "Workspace members" })).getAllByRole("listitem");

const rowParts = (row: HTMLElement) =>
  [".MuiListItemText-primary", ".MuiListItemText-secondary", ".MuiChip-label"].map(
    (part) => row.querySelector(part)?.textContent,
  );

const controlsIn = (scope: HTMLElement) =>
  [...within(scope).queryAllByRole("combobox"), ...within(scope).queryAllByRole("button")].map(
    (control) => control.getAttribute("aria-label"),
  );

async function rowOf(name: string) {
  const row = (await listedRows()).find((item) => rowParts(item)[0] === name);
  if (!row) throw new Error(`No row for ${name}`);
  return row;
}

async function chooseRole(myRole: Schemas["Role"], name: string, role: string) {
  const rendered = renderPanel(myRole);
  await rendered.user.click(await screen.findByRole("combobox", { name: `Role of ${name}` }));
  await rendered.user.click(screen.getByRole("option", { name: role }));
  return rendered;
}

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

test("a Member has no role select", async () => {
  // Arrange
  serveTeam();

  // Act
  renderPanel("member");

  // Assert
  expect(controlsIn(await screen.findByRole("list", { name: "Workspace members" }))).toEqual([]);
});

test.each(MANAGERS)("a %s can change another member's role", async (myRole) => {
  // Arrange
  serveTeam();

  // Act
  renderPanel(myRole);

  // Assert
  expect(controlsIn(await rowOf(MEMBER.name))).toEqual(["Role of Demo Member"]);
});

test.each(MANAGERS)("a %s has no actions on the Owner's row", async (myRole) => {
  // Arrange
  serveTeam();

  // Act
  renderPanel(myRole);

  // Assert
  expect(controlsIn(await rowOf(OWNER.name))).toEqual([]);
});

test("a role change sends the new role for that member", async () => {
  // Arrange
  const changes = serveTeam();

  // Act
  await chooseRole("owner", MEMBER.name, "Moderator");

  // Assert
  await waitFor(() => expect(changes).toEqual([{ user: "member", body: { role: "moderator" } }]));
});

test("a changed role shows once the list is refreshed", async () => {
  // Arrange
  serveTeam();

  // Act
  await chooseRole("owner", MEMBER.name, "Moderator");

  // Assert
  await waitFor(() =>
    expect(screen.getByRole("combobox", { name: "Role of Demo Member" })).toHaveTextContent(
      "Moderator",
    ),
  );
});

test("a refused role change shows the server's message", async () => {
  // Arrange
  serveTeam();
  server.use(
    http.patch("/api/v1/workspaces/{workspace_id}/members/{user_id}", ({ response }) =>
      response(403).json(errorBody("INSUFFICIENT_ROLE", "Only a Moderator may change roles")),
    ),
  );

  // Act
  await chooseRole("owner", MEMBER.name, "Moderator");

  // Assert
  expect(await screen.findByText("Only a Moderator may change roles")).toBeInTheDocument();
});

test("demoting yourself asks first", async () => {
  // Arrange
  serveTeam();

  // Act
  await chooseRole("moderator", MODERATOR.name, "Member");

  // Assert
  expect(
    screen.getByRole("dialog", { name: "Change your role to Member?" }),
  ).toHaveAccessibleDescription(
    "You will no longer manage members or invitations. Only the Owner or another Moderator can make you a Moderator again.",
  );
});

test("a cancelled demotion sends nothing", async () => {
  // Arrange
  const changes = serveTeam();
  const { user } = await chooseRole("moderator", MODERATOR.name, "Member");

  // Act
  await user.click(screen.getByRole("button", { name: "Cancel" }));

  // Assert
  expect(changes).toEqual([]);
});

test("a confirmed demotion is sent", async () => {
  // Arrange
  const changes = serveTeam();
  const { user } = await chooseRole("moderator", MODERATOR.name, "Member");

  // Act
  await user.click(screen.getByRole("button", { name: "Change role" }));

  // Assert
  await waitFor(() => expect(changes).toEqual([{ user: "moderator", body: { role: "member" } }]));
});
