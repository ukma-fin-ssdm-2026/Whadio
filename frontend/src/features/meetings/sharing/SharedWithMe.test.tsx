import { screen } from "@testing-library/react";
import { expect, test, vi } from "vitest";
import type { Schemas } from "@/shared/api/types";
import { page } from "@/shared/testing/fixtures";
import { renderWithProviders } from "@/shared/testing/render";
import { http, server } from "@/shared/testing/server";
import { SharedWithMe } from "./SharedWithMe";

function share(id: string): Schemas["ShareRead"] {
  return { id, redact_speaker_names: false, recipient_user_id: "me", revoked_at: null };
}

function serveReceived(shares: Schemas["ShareRead"][]) {
  server.use(
    http.get("/api/v1/users/me/shares", ({ response }) => response(200).json(page(shares))),
  );
}

test("opening a shared meeting opens that share", async () => {
  // Arrange
  serveReceived([share("first"), share("second")]);
  const onOpen = vi.fn();
  const { user } = renderWithProviders(<SharedWithMe onOpen={onOpen} />);

  // Act
  await user.click(await screen.findByRole("button", { name: /Shared meeting 2/ }));

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
