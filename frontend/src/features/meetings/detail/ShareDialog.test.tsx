import { screen, waitFor, within } from "@testing-library/react";
import { expect, test, vi } from "vitest";
import type { Schemas } from "@/shared/api/types";
import { formatDate } from "@/shared/lib/format";
import { errorBody, page } from "@/shared/testing/fixtures";
import { renderWithProviders } from "@/shared/testing/render";
import { http, server } from "@/shared/testing/server";
import { ShareDialog } from "./ShareDialog";

const LINK = "https://whadio.example/shares/new-share#token=secret";
const CREATED_AT = "2026-11-10T09:00:00Z";
const CREATED = formatDate(CREATED_AT);
const REVOKED_AT = "2026-11-12T10:00:00Z";

function share(changes: Partial<Schemas["ShareRead"]> = {}): Schemas["ShareRead"] {
  return {
    id: "share",
    redact_speaker_names: false,
    recipient_user_id: null,
    revoked_at: null,
    created_at: CREATED_AT,
    ...changes,
  };
}

function serveShares(shares: Schemas["ShareRead"][] = [], pageSize = 100) {
  const created: unknown[] = [];
  const revoked: string[] = [];
  server.use(
    http.get("/api/v1/meetings/{meeting_id}/shares", ({ request, response }) => {
      const start = Number(new URL(request.url).searchParams.get("cursor") ?? 0);
      const end = start + pageSize;
      return response(200).json(
        page(shares.slice(start, end), end < shares.length ? String(end) : null),
      );
    }),
    http.post("/api/v1/meetings/{meeting_id}/shares", async ({ request, response }) => {
      const body = (await request.json()) as Schemas["ShareInput"];
      created.push(body);
      const next = share({ id: "new-share", ...body });
      shares.unshift(next);
      return response(201).json({ ...next, link: LINK });
    }),
    http.delete("/api/v1/shares/{share_id}", ({ params, response }) => {
      revoked.push(params.share_id);
      const revokedShare = shares.find((item) => item.id === params.share_id);
      if (revokedShare) revokedShare.revoked_at = REVOKED_AT;
      return response(204).empty();
    }),
  );
  return { created, revoked };
}

function renderDialog(onOpenRequests: (shareId: string) => void = () => {}) {
  return renderWithProviders(
    <ShareDialog meetingId="meeting" onOpenRequests={onOpenRequests} onClose={() => {}} />,
  );
}

async function confirmRevoke(user: ReturnType<typeof renderDialog>["user"]) {
  const confirm = await screen.findByRole("dialog", { name: "Revoke this share?" });
  await user.click(within(confirm).getByRole("button", { name: "Revoke" }));
}

test("each share shows whether it waits, is approved or was revoked", async () => {
  // Arrange
  serveShares([
    share({ id: "waiting" }),
    share({ id: "approved", recipient_user_id: "recipient" }),
    share({ id: "revoked", recipient_user_id: "recipient", revoked_at: REVOKED_AT }),
  ]);

  // Act
  renderDialog();

  // Assert
  expect(
    within(await screen.findByRole("list", { name: "Your shares" }))
      .getAllByRole("listitem")
      .map((item) => item.textContent),
  ).toEqual([
    `No approved recipient yetCreated ${CREATED} · Speaker names shownRequestsRevoke`,
    `Shared with an approved recipientCreated ${CREATED} · Speaker names shownRevoke`,
    `RevokedCreated ${CREATED} · Speaker names shown`,
  ]);
});

test("Requests opens the access requests of that share", async () => {
  // Arrange
  serveShares([share({ id: "first", revoked_at: REVOKED_AT }), share({ id: "waiting" })]);
  const onOpenRequests = vi.fn();
  const { user } = renderDialog(onOpenRequests);

  // Act
  await user.click(await screen.findByRole("button", { name: "Requests" }));

  // Assert
  expect(onOpenRequests).toHaveBeenCalledWith("waiting");
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

test("a share with a hidden-names setting says so", async () => {
  // Arrange
  serveShares([share({ redact_speaker_names: true })]);

  // Act
  renderDialog();

  // Assert
  expect(await screen.findByText(`Created ${CREATED} · Speaker names hidden`)).toBeInTheDocument();
});

test("each Revoke button names the share by its creation date", async () => {
  // Arrange
  serveShares([
    share({ id: "newer", created_at: "2026-11-11T09:00:00Z" }),
    share({ id: "older", created_at: "2026-11-10T09:00:00Z" }),
  ]);

  // Act
  renderDialog();

  // Assert
  expect(
    within(await screen.findByRole("list", { name: "Your shares" }))
      .getAllByRole("button", { name: /^Revoke share/ })
      .map((button) => button.getAttribute("aria-label")),
  ).toEqual([
    `Revoke share created ${formatDate("2026-11-11T09:00:00Z")}`,
    `Revoke share created ${formatDate("2026-11-10T09:00:00Z")}`,
  ]);
});

test("Revoke asks for confirmation before revoking anything", async () => {
  // Arrange
  const { revoked } = serveShares([share({ id: "first" })]);
  const { user } = renderDialog();

  // Act
  await user.click(await screen.findByRole("button", { name: /^Revoke share/ }));

  // Assert
  expect(await screen.findByRole("dialog", { name: "Revoke this share?" })).toBeInTheDocument();
  expect(revoked).toEqual([]);
});

test("cancelling the confirmation revokes nothing", async () => {
  // Arrange
  const { revoked } = serveShares([share({ id: "first" })]);
  const { user } = renderDialog();
  await user.click(await screen.findByRole("button", { name: /^Revoke share/ }));

  // Act
  await user.click(
    within(await screen.findByRole("dialog", { name: "Revoke this share?" })).getByRole("button", {
      name: "Cancel",
    }),
  );

  // Assert
  await waitFor(() =>
    expect(screen.queryByRole("dialog", { name: "Revoke this share?" })).not.toBeInTheDocument(),
  );
  expect(revoked).toEqual([]);
});

test("revoking a share revokes that share", async () => {
  // Arrange
  const { revoked } = serveShares([share({ id: "first" }), share({ id: "second" })]);
  const { user } = renderDialog();
  const list = await screen.findByRole("list", { name: "Your shares" });

  // Act
  await user.click(
    within(list).getAllByRole("button", { name: /^Revoke share/ })[1] as HTMLElement,
  );
  await confirmRevoke(user);

  // Assert
  await waitFor(() => expect(revoked).toEqual(["second"]));
});

test("a revoked share reads as revoked and loses its Revoke button", async () => {
  // Arrange
  serveShares([share({ id: "first", recipient_user_id: "recipient" })]);
  const { user } = renderDialog();
  await user.click(await screen.findByRole("button", { name: /^Revoke share/ }));

  // Act
  await confirmRevoke(user);

  // Assert
  await waitFor(() =>
    expect(
      within(screen.getByRole("list", { name: "Your shares" })).getByRole("listitem"),
    ).toHaveTextContent(`RevokedCreated ${CREATED} · Speaker names shown`),
  );
});

test("a revoked share is announced", async () => {
  // Arrange
  serveShares([share({ id: "first" })]);
  const { user } = renderDialog();
  await user.click(await screen.findByRole("button", { name: /^Revoke share/ }));

  // Act
  await confirmRevoke(user);

  // Assert
  expect(await screen.findByText("Share revoked.")).toBeInTheDocument();
});

test("a refused revoke shows the server's message and keeps the share live", async () => {
  // Arrange
  serveShares([share({ id: "first" })]);
  server.use(
    http.delete("/api/v1/shares/{share_id}", ({ response }) =>
      response(403).json(
        errorBody("INSUFFICIENT_ROLE", "Your role in this workspace does not allow this"),
      ),
    ),
  );
  const { user } = renderDialog();
  await user.click(await screen.findByRole("button", { name: /^Revoke share/ }));

  // Act
  await confirmRevoke(user);

  // Assert
  expect(await screen.findByRole("alert")).toHaveTextContent(
    "Your role in this workspace does not allow this",
  );
});

test("a newly created share appears in the list", async () => {
  // Arrange
  serveShares();
  const { user } = renderDialog();

  // Act
  await user.click(screen.getByRole("button", { name: "Create link" }));

  // Assert
  expect(
    await within(await screen.findByRole("list", { name: "Your shares" })).findByRole("listitem"),
  ).toHaveTextContent(`No approved recipient yetCreated ${CREATED} · Speaker names shown`);
});

test("only the first page loads until more is asked for", async () => {
  // Arrange
  serveShares([share({ id: "first" }), share({ id: "second" })], 1);

  // Act
  renderDialog();

  // Assert
  expect(
    await within(await screen.findByRole("list", { name: "Your shares" })).findAllByRole(
      "listitem",
    ),
  ).toHaveLength(1);
});

test("Show more loads the next page and disappears after the last", async () => {
  // Arrange
  serveShares([share({ id: "first" }), share({ id: "second" })], 1);
  const { user } = renderDialog();

  // Act
  await user.click(await screen.findByRole("button", { name: "Show more" }));

  // Assert
  await waitFor(() => expect(screen.getAllByRole("listitem")).toHaveLength(2));
  expect(screen.queryByRole("button", { name: "Show more" })).not.toBeInTheDocument();
});

test("a share on the second page can be revoked", async () => {
  // Arrange
  const { revoked } = serveShares([share({ id: "first" }), share({ id: "second" })], 1);
  const { user } = renderDialog();
  await user.click(await screen.findByRole("button", { name: "Show more" }));
  await waitFor(() => expect(screen.getAllByRole("listitem")).toHaveLength(2));
  const list = screen.getByRole("list", { name: "Your shares" });

  // Act
  await user.click(
    within(list).getAllByRole("button", { name: /^Revoke share/ })[1] as HTMLElement,
  );
  await confirmRevoke(user);

  // Assert
  await waitFor(() => expect(revoked).toEqual(["second"]));
  await waitFor(() =>
    expect(within(list).getAllByRole("listitem")[1]).toHaveTextContent("Revoked"),
  );
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

test("a failed load of the shares shows the server's message", async () => {
  // Arrange
  server.use(
    http.get("/api/v1/meetings/{meeting_id}/shares", ({ response }) =>
      response(404).json(errorBody("NOT_FOUND", "Meeting not found")),
    ),
  );

  // Act
  renderDialog();

  // Assert
  expect(await screen.findByRole("alert")).toHaveTextContent("Meeting not found");
});

test("escape keeps the dialog open while a share is being created", async () => {
  // Arrange
  serveShares();
  server.use(
    http.post("/api/v1/meetings/{meeting_id}/shares", () => new Promise<Response>(() => {})),
  );
  const onClose = vi.fn();
  const { user } = renderWithProviders(
    <ShareDialog meetingId="meeting" onOpenRequests={() => {}} onClose={onClose} />,
  );
  await user.click(screen.getByRole("button", { name: "Create link" }));
  await waitFor(() => expect(screen.getByRole("button", { name: "Close" })).toBeDisabled());
  await user.click(screen.getByRole("checkbox", { name: "Hide speaker names" }));

  // Act
  await user.keyboard("{Escape}");

  // Assert
  expect(onClose).not.toHaveBeenCalled();
});

test("Close is disabled while a share is being created", async () => {
  // Arrange
  serveShares();
  server.use(
    http.post("/api/v1/meetings/{meeting_id}/shares", () => new Promise<Response>(() => {})),
  );
  const { user } = renderDialog();

  // Act
  await user.click(screen.getByRole("button", { name: "Create link" }));

  // Assert
  await waitFor(() => expect(screen.getByRole("button", { name: "Close" })).toBeDisabled());
});

test("Revoke is disabled while a share is being created", async () => {
  // Arrange
  serveShares([share({ id: "first" })]);
  server.use(
    http.post("/api/v1/meetings/{meeting_id}/shares", () => new Promise<Response>(() => {})),
  );
  const { user } = renderDialog();
  const revoke = await screen.findByRole("button", { name: /^Revoke share/ });

  // Act
  await user.click(screen.getByRole("button", { name: "Create link" }));

  // Assert
  await waitFor(() => expect(revoke).toBeDisabled());
});

test("Revoke is disabled on the other shares while a revoke is pending", async () => {
  // Arrange
  serveShares([share({ id: "first" }), share({ id: "second" })]);
  server.use(http.delete("/api/v1/shares/{share_id}", () => new Promise<Response>(() => {})));
  const { user } = renderDialog();
  const [first, second] = await screen.findAllByRole("button", { name: /^Revoke share/ });
  await user.click(first as HTMLElement);

  // Act
  await confirmRevoke(user);

  // Assert
  await waitFor(() => expect(second).toBeDisabled());
});
