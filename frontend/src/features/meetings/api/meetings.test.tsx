import { renderHook, waitFor } from "@testing-library/react";
import type { ReactNode } from "react";
import { afterEach, expect, test, vi } from "vitest";
import { apiClient } from "@/shared/api/client";
import {
  errorBody,
  meetingRead,
  meetingSummary,
  noteRead,
  page,
  transcriptRead,
} from "@/shared/testing/fixtures";
import { createTestQueryClient, TestProviders } from "@/shared/testing/render";
import { http, server } from "@/shared/testing/server";
import { meetingQueries, useUploadMeeting } from "./meetings";

afterEach(() => {
  vi.restoreAllMocks();
});

const RECORDING = new File(["RIFF"], "standup.wav", { type: "audio/wav" });

function serveUpload() {
  server.use(
    http.post("/api/v1/workspaces/{workspace_id}/meetings", ({ response }) =>
      response(201).json(meetingRead({ id: "created" })),
    ),
  );
}

// jsdom's FormData does not survive Node's Request, so the body is read before serialisation;
// shared/api/body.test.ts covers the form itself.
const sentBody = (post: { mock: { calls: unknown[][] } }) => post.mock.calls[0]?.[1];

function renderUpload() {
  const queryClient = createTestQueryClient();
  queryClient.setQueryData(meetingQueries.latest("workspace").queryKey, page([meetingSummary()]));
  queryClient.setQueryData(meetingQueries.latest("other").queryKey, page([meetingSummary()]));
  const wrapper = ({ children }: { children: ReactNode }) => (
    <TestProviders queryClient={queryClient}>{children}</TestProviders>
  );
  const { result } = renderHook(() => useUploadMeeting("workspace"), { wrapper });
  return { result, queryClient };
}

test("both list shapes sit under their workspace", () => {
  // Act
  const keys = [
    meetingQueries.list("alpha", "sync").queryKey,
    meetingQueries.latest("alpha", "sync").queryKey,
  ];

  // Assert
  expect(keys).toEqual([
    ["meetings", "list", "alpha", "pages", { name: "sync" }],
    ["meetings", "list", "alpha", "latest", { name: "sync" }],
  ]);
});

test("a name filter gets its own cache entry", () => {
  // Act
  const keys = [meetingQueries.list("alpha").queryKey, meetingQueries.list("alpha", "x").queryKey];

  // Assert
  expect(keys[0]).not.toEqual(keys[1]);
});

test("a meeting's content sits under its detail key", () => {
  // Arrange
  const meeting = { id: "alpha", state: "processed", recordingAvailable: true } as const;

  // Act
  const keys = [
    meetingQueries.detail("alpha").queryKey,
    meetingQueries.transcript(meeting, "revision").queryKey,
    meetingQueries.notes(meeting).queryKey,
    meetingQueries.recording(meeting).queryKey,
  ];

  // Assert
  expect(keys).toEqual([
    ["meetings", "detail", "alpha"],
    ["meetings", "detail", "alpha", "transcript", { revisionId: "revision" }],
    ["meetings", "detail", "alpha", "notes"],
    ["meetings", "detail", "alpha", "recording"],
  ]);
});

test("each transcript revision gets its own cache entry", () => {
  // Arrange
  const meeting = { id: "alpha", state: "processed" } as const;

  // Act
  const keys = [
    meetingQueries.transcript(meeting, null).queryKey,
    meetingQueries.transcript(meeting, "original").queryKey,
  ];

  // Assert
  expect(keys[0]).not.toEqual(keys[1]);
});

test.for([
  ["processed", true, true],
  ["failed", true, false],
  ["recording", false, false],
  ["queued", false, false],
  ["processing", false, false],
] as const)(
  "%s meeting enables its transcript: %s, its notes: %s",
  ([state, transcript, notes]) => {
    // Act
    const flags = [
      meetingQueries.transcript({ id: "alpha", state }, null).enabled,
      meetingQueries.notes({ id: "alpha", state }).enabled,
    ];

    // Assert
    expect(flags).toEqual([transcript, notes]);
  },
);

function captureTranscriptQuery() {
  const searches: string[] = [];
  server.use(
    http.get("/api/v1/meetings/{meeting_id}/transcript", ({ request, response }) => {
      searches.push(new URL(request.url).search);
      return response(200).json(transcriptRead());
    }),
  );
  return searches;
}

test.for([
  ["names the requested revision", "revision", "?revision_id=revision"],
  ["sends no revision for the current one", null, ""],
] as const)("transcript request %s", async ([, revisionId, search]) => {
  // Arrange
  const searches = captureTranscriptQuery();
  const query = meetingQueries.transcript({ id: "meeting", state: "processed" }, revisionId);

  // Act
  await createTestQueryClient().fetchQuery(query);

  // Assert
  expect(searches).toEqual([search]);
});

function refuseTranscript() {
  server.use(
    http.get("/api/v1/meetings/{meeting_id}/transcript", ({ response }) =>
      response(409).json(errorBody("NOT_TRANSCRIBED", "Not transcribed")),
    ),
  );
}

test("a meeting with no transcript answers with none", async () => {
  // Arrange
  refuseTranscript();
  const query = meetingQueries.transcript({ id: "meeting", state: "failed" }, null);

  // Act
  const transcript = await createTestQueryClient().fetchQuery(query);

  // Assert
  expect(transcript).toBeNull();
});

test("a named revision of a meeting with no transcript is an error", async () => {
  // Arrange
  refuseTranscript();
  const query = meetingQueries.transcript({ id: "meeting", state: "failed" }, "original");

  // Act
  const request = createTestQueryClient().fetchQuery(query);

  // Assert
  await expect(request).rejects.toMatchObject({ code: "NOT_TRANSCRIBED" });
});

test("a transcript request that fails otherwise stays an error", async () => {
  // Arrange
  server.use(
    http.get("/api/v1/meetings/{meeting_id}/transcript", ({ response }) =>
      response(404).json(errorBody("NOT_FOUND", "Meeting not found")),
    ),
  );
  const query = meetingQueries.transcript({ id: "meeting", state: "failed" }, null);

  // Act
  const request = createTestQueryClient().fetchQuery(query);

  // Assert
  await expect(request).rejects.toMatchObject({ code: "NOT_FOUND" });
});

test("notes query selects the newest version", async () => {
  // Arrange
  server.use(
    http.get("/api/v1/meetings/{meeting_id}/notes", ({ response }) =>
      response(200).json(page([noteRead({ content: "Newest" })])),
    ),
  );
  const query = meetingQueries.notes({ id: "meeting", state: "processed" });

  // Act
  const notes = await createTestQueryClient().fetchQuery(query);

  // Assert
  expect(query.select?.(notes)?.content).toBe("Newest");
});

test("a meeting without notes selects none", async () => {
  // Arrange
  server.use(
    http.get("/api/v1/meetings/{meeting_id}/notes", ({ response }) => response(200).json(page([]))),
  );
  const query = meetingQueries.notes({ id: "meeting", state: "processed" });

  // Act
  const notes = await createTestQueryClient().fetchQuery(query);

  // Assert
  expect(query.select?.(notes)).toBeNull();
});

test("an upload trims the name", async () => {
  // Arrange
  serveUpload();
  const post = vi.spyOn(apiClient, "POST");
  const { result } = renderUpload();

  // Act
  await result.current.mutateAsync({ file: RECORDING, name: "  Standup  " });

  // Assert
  expect(sentBody(post)).toMatchObject({ body: { file: RECORDING, name: "Standup" } });
});

test("an upload leaves out a blank name", async () => {
  // Arrange
  serveUpload();
  const post = vi.spyOn(apiClient, "POST");
  const { result } = renderUpload();

  // Act
  await result.current.mutateAsync({ file: RECORDING, name: "   " });

  // Assert
  expect(sentBody(post)).toMatchObject({ body: { name: undefined } });
});

test("an upload returns the new meeting", async () => {
  // Arrange
  serveUpload();
  const { result } = renderUpload();

  // Act
  const created = await result.current.mutateAsync({ file: RECORDING, name: "" });

  // Assert
  expect(created.id).toBe("created");
});

test("an upload marks its workspace's meetings for a refetch", async () => {
  // Arrange
  serveUpload();
  const { result, queryClient } = renderUpload();

  // Act
  result.current.mutate({ file: RECORDING, name: "" });

  // Assert
  await waitFor(() =>
    expect(
      queryClient.getQueryState(meetingQueries.latest("workspace").queryKey)?.isInvalidated,
    ).toBe(true),
  );
});

test("an upload leaves other workspaces alone", async () => {
  // Arrange
  serveUpload();
  const { result, queryClient } = renderUpload();

  // Act
  await result.current.mutateAsync({ file: RECORDING, name: "" });

  // Assert
  expect(queryClient.getQueryState(meetingQueries.latest("other").queryKey)?.isInvalidated).toBe(
    false,
  );
});

test("a failed upload refreshes nothing", async () => {
  // Arrange
  server.use(
    http.post("/api/v1/workspaces/{workspace_id}/meetings", ({ response }) =>
      response(415).json(errorBody("UNSUPPORTED_MEDIA_TYPE", "Not a recording")),
    ),
  );
  const { result, queryClient } = renderUpload();

  // Act
  await expect(result.current.mutateAsync({ file: RECORDING, name: "" })).rejects.toThrow();

  // Assert
  expect(
    queryClient.getQueryState(meetingQueries.latest("workspace").queryKey)?.isInvalidated,
  ).toBe(false);
});
