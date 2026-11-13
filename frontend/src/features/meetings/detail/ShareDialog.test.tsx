import { screen, waitFor, within } from "@testing-library/react";
import { expect, test } from "vitest";
import type { Schemas } from "@/shared/api/types";
import { errorBody, page } from "@/shared/testing/fixtures";
import { renderWithProviders } from "@/shared/testing/render";
import { http, server } from "@/shared/testing/server";
import { ShareDialog } from "./ShareDialog";

const LINK = "https://whadio.example/shares/new-share#token=secret";

function share(changes: Partial<Schemas["ShareRead"]> = {}): Schemas["ShareRead"] {
  return {
    id: "share",
    redact_speaker_names: false,
    recipient_user_id: null,
    revoked_at: null,
    ...changes,
  };
}

function serveShares(shares: Schemas["ShareRead"][] = []) {
  const created: unknown[] = [];
  const revoked: string[] = [];
  server.use(
    http.get("/api/v1/meetings/{meeting_id}/shares", ({ response }) =>
      response(200).json(page(shares)),
    ),
    http.post("/api/v1/meetings/{meeting_id}/shares", async ({ request, response }) => {
      const body = (await request.json()) as Schemas["ShareInput"];
      created.push(body);
      return response(201).json({ ...share({ id: "new-share", ...body }), link: LINK });
    }),
    http.delete("/api/v1/shares/{share_id}", ({ params, response }) => {
      revoked.push(params.share_id);
      return response(204).empty();
    }),
  );
  return { created, revoked };
}

function renderDialog() {
  return renderWithProviders(
    <ShareDialog
      meetingId="meeting"
      requestsHref={(shareId) => `/shares/${shareId}/access-requests`}
      onClose={() => {}}
    />,
  );
}

test("each share shows whether it waits, is approved or was revoked", async () => {
  // Arrange
  serveShares([
    share({ id: "waiting" }),
    share({ id: "approved", recipient_user_id: "recipient" }),
    share({ id: "revoked", revoked_at: "2026-11-12T10:00:00Z" }),
  ]);

  // Act
  renderDialog();

  // Assert
  expect(
    within(await screen.findByRole("list", { name: "Your shares" }))
      .getAllByRole("listitem")
      .map((item) => item.textContent),
  ).toEqual([
    "Waiting for someone to open the linkSpeaker names shownRequestsRevoke",
    "Shared with an approved recipientSpeaker names shownRevoke",
    "RevokedSpeaker names shown",
  ]);
});

test("a waiting share links to its access requests", async () => {
  // Arrange
  serveShares([share({ id: "waiting" })]);

  // Act
  renderDialog();

  // Assert
  expect(await screen.findByRole("link", { name: "Requests" })).toHaveAttribute(
    "href",
    "/shares/waiting/access-requests",
  );
});

test("a share hides speaker names when asked to", async () => {
  // Arrange
  const { created } = serveShares();
  const { user } = renderDialog();

  // Act
  await user.click(screen.getByRole("checkbox", { name: "Hide speaker names" }));
  await user.click(screen.getByRole("button", { name: "Create link" }));

  // Assert
  await waitFor(() => expect(created).toEqual([{ redact_speaker_names: true }]));
});

test("a share shows speaker names by default", async () => {
  // Arrange
  const { created } = serveShares();
  const { user } = renderDialog();

  // Act
  await user.click(screen.getByRole("button", { name: "Create link" }));

  // Assert
  await waitFor(() => expect(created).toEqual([{ redact_speaker_names: false }]));
});

test("a created share's link is shown to copy", async () => {
  // Arrange
  serveShares();
  const { user } = renderDialog();

  // Act
  await user.click(screen.getByRole("button", { name: "Create link" }));

  // Assert
  expect(await screen.findByRole("textbox", { name: "Share link" })).toHaveValue(LINK);
});

test("once a link is shown no second one is offered", async () => {
  // Arrange
  serveShares();
  const { user } = renderDialog();

  // Act
  await user.click(screen.getByRole("button", { name: "Create link" }));
  await screen.findByRole("textbox", { name: "Share link" });

  // Assert
  expect(screen.queryByRole("button", { name: "Create link" })).not.toBeInTheDocument();
});

test("revoking a share revokes that share", async () => {
  // Arrange
  const { revoked } = serveShares([share({ id: "first" }), share({ id: "second" })]);
  const { user } = renderDialog();
  const list = await screen.findByRole("list", { name: "Your shares" });

  // Act
  await user.click(within(list).getAllByRole("button", { name: "Revoke" })[1] as HTMLElement);

  // Assert
  await waitFor(() => expect(revoked).toEqual(["second"]));
});

test("a refused share shows the server's message", async () => {
  // Arrange
  serveShares();
  server.use(
    http.post("/api/v1/meetings/{meeting_id}/shares", ({ response }) =>
      response(404).json(errorBody("NOT_FOUND", "Meeting not found")),
    ),
  );
  const { user } = renderDialog();

  // Act
  await user.click(screen.getByRole("button", { name: "Create link" }));

  // Assert
  expect(await screen.findByRole("alert")).toHaveTextContent("Meeting not found");
});
