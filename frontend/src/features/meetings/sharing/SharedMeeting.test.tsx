import { screen } from "@testing-library/react";
import { expect, test } from "vitest";
import { errorBody, noteRead, page, transcriptRead } from "@/shared/testing/fixtures";
import { renderWithProviders } from "@/shared/testing/render";
import { http, server } from "@/shared/testing/server";
import { SharedMeeting } from "./SharedMeeting";

function serveShare() {
  server.use(
    http.get("/api/v1/shares/{share_id}/transcript", ({ response }) =>
      response(200).json(
        transcriptRead({
          speakers: [{ id: "speaker", display_name: "Speaker 1", is_unnamed: true }],
          segments: [
            {
              id: "one",
              speaker_id: "speaker",
              start_seconds: 65,
              end_seconds: 70,
              text: "Budget agreed",
            },
          ],
        }),
      ),
    ),
    http.get("/api/v1/shares/{share_id}/notes", ({ response }) =>
      response(200).json(page([noteRead({ content: "Shared notes" })])),
    ),
  );
}

test("a recipient reads the shared notes", async () => {
  // Arrange
  serveShare();

  // Act
  renderWithProviders(<SharedMeeting shareId="share" />);

  // Assert
  expect(await screen.findByText("Shared notes")).toBeInTheDocument();
});

test("a recipient reads the shared transcript", async () => {
  // Arrange
  serveShare();

  // Act
  renderWithProviders(<SharedMeeting shareId="share" />);

  // Assert
  expect(await screen.findByText("Budget agreed")).toBeInTheDocument();
});

test("a recipient gets no recording, export, share or edit action", async () => {
  // Arrange
  serveShare();

  // Act
  renderWithProviders(<SharedMeeting shareId="share" />);
  await screen.findByText("Shared notes");

  // Assert
  expect(screen.queryAllByRole("button")).toEqual([]);
});

test("an empty transcript is not reported as a failed search", async () => {
  // Arrange
  server.use(
    http.get("/api/v1/shares/{share_id}/transcript", ({ response }) =>
      response(200).json(transcriptRead()),
    ),
    http.get("/api/v1/shares/{share_id}/notes", ({ response }) => response(200).json(page([]))),
  );

  // Act
  renderWithProviders(<SharedMeeting shareId="share" />);

  // Assert
  expect(await screen.findByText("The transcript has no text.")).toBeInTheDocument();
});

test("a revoked share says it was revoked", async () => {
  // Arrange
  server.use(
    http.get("/api/v1/shares/{share_id}/transcript", ({ response }) =>
      response(410).json(errorBody("SHARE_REVOKED", "Share revoked")),
    ),
    http.get("/api/v1/shares/{share_id}/notes", ({ response }) =>
      response(410).json(errorBody("SHARE_REVOKED", "Share revoked")),
    ),
  );

  // Act
  renderWithProviders(<SharedMeeting shareId="share" />);

  // Assert
  expect(
    await screen.findByText("The person who shared this meeting revoked it."),
  ).toBeInTheDocument();
});

test("a share bound to someone else shows no content", async () => {
  // Arrange
  server.use(
    http.get("/api/v1/shares/{share_id}/transcript", ({ response }) =>
      response(404).json(errorBody("NOT_FOUND", "Not found")),
    ),
    http.get("/api/v1/shares/{share_id}/notes", ({ response }) =>
      response(404).json(errorBody("NOT_FOUND", "Not found")),
    ),
  );

  // Act
  renderWithProviders(<SharedMeeting shareId="share" />);

  // Assert
  expect(await screen.findByText(/This share is not open to your account/)).toBeInTheDocument();
});
