import { focusManager } from "@tanstack/react-query";
import { act, screen, waitFor } from "@testing-library/react";
import { afterEach, expect, test, vi } from "vitest";
import { errorBody, meetingRead } from "@/shared/testing/fixtures";
import { renderWithProviders } from "@/shared/testing/render";
import { http, server } from "@/shared/testing/server";
import { meetingQueries } from "../api/meetings";
import { mapMeeting } from "../model";
import { RecordingPlayer } from "./RecordingPlayer";

const LINK = "https://storage.example/recording?signature=secret";
const FOUR_MINUTES_MS = 4 * 60_000;
const FIVE_MINUTES_MS = 5 * 60_000;

const availableMeeting = mapMeeting(meetingRead({ recording_available: true }));
const unavailableMeeting = mapMeeting(meetingRead({ recording_available: false }));

afterEach(() => {
  focusManager.setFocused(undefined);
  vi.useRealTimers();
});

function serveLink() {
  const traffic = { requests: 0 };
  server.use(
    http.get("/api/v1/meetings/{meeting_id}/recording", ({ response }) => {
      traffic.requests += 1;
      return response(200).json({ url: LINK, expires_at: "2026-10-25T10:05:00Z" });
    }),
  );
  return traffic;
}

function player() {
  const video = screen.getByLabelText("Weekly sync recording");
  return video.getAttribute("src");
}

test("an available recording plays from its link", async () => {
  // Arrange
  serveLink();

  // Act
  renderWithProviders(<RecordingPlayer meeting={availableMeeting} />);

  // Assert
  await waitFor(() => expect(player()).toBe(LINK));
});

test("an unavailable recording requests no link", async () => {
  // Arrange
  const traffic = serveLink();

  // Act
  renderWithProviders(<RecordingPlayer meeting={mapMeeting(meetingRead())} />);

  // Assert
  await screen.findByText("Recording is not available");
  expect(traffic.requests).toBe(0);
});

test("a refused link shows why", async () => {
  // Arrange
  server.use(
    http.get("/api/v1/meetings/{meeting_id}/recording", ({ response }) =>
      response(404).json(errorBody("NOT_FOUND", "Recording not found")),
    ),
  );

  // Act
  renderWithProviders(<RecordingPlayer meeting={availableMeeting} />);

  // Assert
  expect(await screen.findByRole("alert")).toHaveTextContent("Recording not found");
});

test("a recording that goes away stops playing", async () => {
  // Arrange
  serveLink();
  const { rerender } = renderWithProviders(<RecordingPlayer meeting={availableMeeting} />);
  await screen.findByLabelText("Weekly sync recording");

  // Act
  rerender(<RecordingPlayer meeting={unavailableMeeting} />);

  // Assert
  expect(screen.queryByLabelText("Weekly sync recording")).not.toBeInTheDocument();
});

async function refuseLinkThenLoseRecording() {
  server.use(
    http.get("/api/v1/meetings/{meeting_id}/recording", ({ response }) =>
      response(410).json(errorBody("RECORDING_DELETED", "Recording deleted")),
    ),
  );
  const { rerender } = renderWithProviders(<RecordingPlayer meeting={availableMeeting} />);
  await screen.findByRole("alert");
  rerender(<RecordingPlayer meeting={unavailableMeeting} />);
}

test("a recording that goes away says so instead of keeping the refusal", async () => {
  // Act
  await refuseLinkThenLoseRecording();

  // Assert
  expect(screen.getByText("Recording is not available")).toBeInTheDocument();
});

test("a recording that goes away shows no alert", async () => {
  // Act
  await refuseLinkThenLoseRecording();

  // Assert
  expect(screen.queryByRole("alert")).not.toBeInTheDocument();
});

test("coming back to the window with a stale link keeps the player's source", async () => {
  // Arrange
  vi.useFakeTimers({ shouldAdvanceTime: true });
  const traffic = serveLink();
  renderWithProviders(<RecordingPlayer meeting={availableMeeting} />);
  await screen.findByLabelText("Weekly sync recording");
  await act(() => vi.advanceTimersByTimeAsync(FOUR_MINUTES_MS + 1));

  // Act
  focusManager.setFocused(false);
  focusManager.setFocused(true);
  await act(() => vi.advanceTimersByTimeAsync(0));

  // Assert
  expect(traffic.requests).toBe(1);
});

test("a link stays fresh when the tab is reopened within four minutes", async () => {
  // Arrange
  vi.useFakeTimers({ shouldAdvanceTime: true });
  const traffic = serveLink();
  const { unmount, queryClient } = renderWithProviders(
    <RecordingPlayer meeting={availableMeeting} />,
  );
  await screen.findByLabelText("Weekly sync recording");
  unmount();
  await act(() => vi.advanceTimersByTimeAsync(FOUR_MINUTES_MS - 1000));

  // Act
  renderWithProviders(<RecordingPlayer meeting={availableMeeting} />, queryClient);
  await act(() => vi.advanceTimersByTimeAsync(0));

  // Assert
  expect(traffic.requests).toBe(1);
});

test("a stale link is replaced when the tab is reopened", async () => {
  // Arrange
  vi.useFakeTimers({ shouldAdvanceTime: true });
  const traffic = serveLink();
  const { unmount, queryClient } = renderWithProviders(
    <RecordingPlayer meeting={availableMeeting} />,
  );
  await screen.findByLabelText("Weekly sync recording");
  unmount();
  await act(() => vi.advanceTimersByTimeAsync(FOUR_MINUTES_MS + 1));

  // Act
  renderWithProviders(<RecordingPlayer meeting={availableMeeting} />, queryClient);
  await act(() => vi.advanceTimersByTimeAsync(0));

  // Assert
  expect(traffic.requests).toBe(2);
});

test("a link leaves the cache by the end of its life", async () => {
  // Arrange
  vi.useFakeTimers({ shouldAdvanceTime: true });
  serveLink();
  const { unmount, queryClient } = renderWithProviders(
    <RecordingPlayer meeting={availableMeeting} />,
  );
  await screen.findByLabelText("Weekly sync recording");
  unmount();

  // Act
  await act(() => vi.advanceTimersByTimeAsync(FIVE_MINUTES_MS));

  // Assert
  expect(
    queryClient.getQueryData(meetingQueries.recording(availableMeeting).queryKey),
  ).toBeUndefined();
});
