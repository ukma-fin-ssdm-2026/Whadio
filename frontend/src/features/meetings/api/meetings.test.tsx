import { renderHook, waitFor } from "@testing-library/react";
import type { ReactNode } from "react";
import { afterEach, expect, test, vi } from "vitest";
import { apiClient } from "@/shared/api/client";
import { errorBody, meetingRead, meetingSummary, page } from "@/shared/testing/fixtures";
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
