import { screen } from "@testing-library/react";
import { expect, test } from "vitest";
import { errorBody, noteRead, page, transcriptRead } from "@/shared/testing/fixtures";
import { renderWithProviders } from "@/shared/testing/render";
import { http, server } from "@/shared/testing/server";
import { SharedMeeting } from "./SharedMeeting";

const SHARE_ID = "11111111-1111-4111-8111-111111111111";

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
  renderWithProviders(<SharedMeeting shareId={SHARE_ID} />);

  // Assert
  expect(await screen.findByText("Shared notes")).toBeInTheDocument();
});

test("a recipient reads the shared transcript", async () => {
  // Arrange
  serveShare();

  // Act
  renderWithProviders(<SharedMeeting shareId={SHARE_ID} />);

  // Assert
  expect(await screen.findByText("Budget agreed")).toBeInTheDocument();
});

test("a recipient sees who said each segment", async () => {
  // Arrange
  serveShare();

  // Act
  renderWithProviders(<SharedMeeting shareId={SHARE_ID} />);

  // Assert
  expect(await screen.findByText("Speaker 1")).toBeInTheDocument();
});

test("searching the transcript keeps the segments that match", async () => {
  // Arrange
  serveShare();
  const { user } = renderWithProviders(<SharedMeeting shareId={SHARE_ID} />);
  await screen.findByText("Budget agreed");

  // Act
  await user.type(screen.getByPlaceholderText("Search transcript"), "budget");

  // Assert
  expect(screen.getByText("Budget agreed")).toBeInTheDocument();
});

test("searching the transcript hides the segments that do not match", async () => {
  // Arrange
  serveShare();
  const { user } = renderWithProviders(<SharedMeeting shareId={SHARE_ID} />);
  await screen.findByText("Budget agreed");

  // Act
  await user.type(screen.getByPlaceholderText("Search transcript"), "zebra");

  // Assert
  expect(screen.queryByText("Budget agreed")).not.toBeInTheDocument();
});

test("a search with no match says so", async () => {
  // Arrange
  serveShare();
  const { user } = renderWithProviders(<SharedMeeting shareId={SHARE_ID} />);
  await screen.findByText("Budget agreed");

  // Act
  await user.type(screen.getByPlaceholderText("Search transcript"), "zebra");

  // Assert
  expect(screen.getByText("No transcript matches your search.")).toBeInTheDocument();
});

test("a meeting without a transcript yet says so instead of failing", async () => {
  // Arrange
  server.use(
    http.get("/api/v1/shares/{share_id}/transcript", ({ response }) =>
      response(409).json(errorBody("NOT_TRANSCRIBED", "Not transcribed")),
    ),
    http.get("/api/v1/shares/{share_id}/notes", ({ response }) => response(200).json(page([]))),
  );

  // Act
  renderWithProviders(<SharedMeeting shareId={SHARE_ID} />);

  // Assert
  expect(await screen.findByText("Transcript is not available yet.")).toBeInTheDocument();
});

test("a meeting without a transcript yet shows no error banner", async () => {
  // Arrange
  server.use(
    http.get("/api/v1/shares/{share_id}/transcript", ({ response }) =>
      response(409).json(errorBody("NOT_TRANSCRIBED", "Not transcribed")),
    ),
    http.get("/api/v1/shares/{share_id}/notes", ({ response }) => response(200).json(page([]))),
  );

  // Act
  renderWithProviders(<SharedMeeting shareId={SHARE_ID} />);
  await screen.findByText("Transcript is not available yet.");

  // Assert
  expect(screen.queryByRole("alert")).not.toBeInTheDocument();
});

test("notes that fail to load show the failure", async () => {
  // Arrange
  serveShare();
  server.use(
    http.get("/api/v1/shares/{share_id}/notes", ({ response }) =>
      response(503).json(errorBody("INTERNAL_ERROR", "Notes unavailable")),
    ),
  );

  // Act
  renderWithProviders(<SharedMeeting shareId={SHARE_ID} />);

  // Assert
  expect(await screen.findByText("Notes unavailable")).toBeInTheDocument();
});

test("a share id that is not a share is not open to the account", () => {
  // Act
  renderWithProviders(<SharedMeeting shareId="not-a-share" />);

  // Assert
  expect(screen.getByText(/This share is not open to your account/)).toBeInTheDocument();
});

test("a recipient gets no recording, export, share or edit action", async () => {
  // Arrange
  serveShare();

  // Act
  renderWithProviders(<SharedMeeting shareId={SHARE_ID} />);
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
  renderWithProviders(<SharedMeeting shareId={SHARE_ID} />);

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
  renderWithProviders(<SharedMeeting shareId={SHARE_ID} />);

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
  renderWithProviders(<SharedMeeting shareId={SHARE_ID} />);

  // Assert
  expect(await screen.findByText(/This share is not open to your account/)).toBeInTheDocument();
});
