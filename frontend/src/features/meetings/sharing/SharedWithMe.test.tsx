import { screen, waitFor } from "@testing-library/react";
import { expect, test, vi } from "vitest";
import type { Schemas } from "@/shared/api/types";
import { formatDate } from "@/shared/lib/format";
import { errorBody, page } from "@/shared/testing/fixtures";
import { renderWithProviders } from "@/shared/testing/render";
import { http, server } from "@/shared/testing/server";
import { SharedWithMe } from "./SharedWithMe";

const FIRST_AT = "2026-11-17T10:00:00Z";
const SECOND_AT = "2026-11-12T08:00:00Z";

function share(id: string, changes: Partial<Schemas["ShareRead"]> = {}): Schemas["ShareRead"] {
  return {
    id,
    redact_speaker_names: false,
    recipient_user_id: "me",
    revoked_at: null,
    created_at: FIRST_AT,
    ...changes,
  };
}

function serveReceived(shares: Schemas["ShareRead"][], pageSize = 100) {
  server.use(
    http.get("/api/v1/users/me/shares", ({ request, response }) => {
      const start = Number(new URL(request.url).searchParams.get("cursor") ?? 0);
      const end = start + pageSize;
      return response(200).json(
        page(shares.slice(start, end), end < shares.length ? String(end) : null),
      );
    }),
  );
}

test("opening a shared meeting opens that share", async () => {
  // Arrange
  serveReceived([share("first"), share("second", { created_at: SECOND_AT })]);
  const onOpen = vi.fn();
  const { user } = renderWithProviders(<SharedWithMe onOpen={onOpen} />);

  // Act
  await user.click(await screen.findByRole("button", { name: new RegExp(formatDate(SECOND_AT)) }));

  // Assert
  expect(onOpen).toHaveBeenCalledWith("second");
});

test("each shared meeting is labelled with the date it was shared", async () => {
  // Arrange
  serveReceived([share("first")]);

  // Act
  renderWithProviders(<SharedWithMe onOpen={() => {}} />);

  // Assert
  expect(await screen.findByText(`Shared ${formatDate(FIRST_AT)}`)).toBeInTheDocument();
});

test("a share with hidden speaker names says so", async () => {
  // Arrange
  serveReceived([share("first", { redact_speaker_names: true })]);

  // Act
  renderWithProviders(<SharedWithMe onOpen={() => {}} />);

  // Assert
  expect(await screen.findByText("Speaker names hidden")).toBeInTheDocument();
});

test("a share with shown speaker names says so", async () => {
  // Arrange
  serveReceived([share("first")]);

  // Act
  renderWithProviders(<SharedWithMe onOpen={() => {}} />);

  // Assert
  expect(await screen.findByText("Speaker names shown")).toBeInTheDocument();
});

test("a failed list shows the failure", async () => {
  // Arrange
  server.use(
    http.get("/api/v1/users/me/shares", ({ response }) =>
      response(503).json(errorBody("INTERNAL_ERROR", "Shares unavailable")),
    ),
  );

  // Act
  renderWithProviders(<SharedWithMe onOpen={() => {}} />);

  // Assert
  expect(await screen.findByText("Shares unavailable")).toBeInTheDocument();
});

test("a share on the second page can be opened", async () => {
  // Arrange
  serveReceived([share("first"), share("second", { created_at: SECOND_AT })], 1);
  const onOpen = vi.fn();
  const { user } = renderWithProviders(<SharedWithMe onOpen={onOpen} />);
  await user.click(await screen.findByRole("button", { name: "Show more" }));
  await waitFor(() => expect(screen.getAllByRole("listitem")).toHaveLength(2));

  // Act
  await user.click(screen.getByRole("button", { name: new RegExp(formatDate(SECOND_AT)) }));

  // Assert
  expect(onOpen).toHaveBeenCalledWith("second");
});

test("nothing shared says so", async () => {
  // Arrange
  serveReceived([]);

  // Act
  renderWithProviders(<SharedWithMe onOpen={() => {}} />);

  // Assert
  expect(await screen.findByText("Nothing shared with you yet")).toBeInTheDocument();
});
