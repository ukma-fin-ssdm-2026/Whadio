import { renderHook } from "@testing-library/react";
import type { ReactNode } from "react";
import { expect, test } from "vitest";
import { errorBody, meetingSummary, page } from "@/shared/testing/fixtures";
import { createTestQueryClient, TestProviders } from "@/shared/testing/render";
import { http, server } from "@/shared/testing/server";
import { accessQueries, useSetMeetingAccess } from "./access";
import { meetingQueries } from "./meetings";

const RESTRICTED = { access_mode: "restricted" as const, member_ids: ["moderator"] };

function seedCaches() {
  const queryClient = createTestQueryClient();
  queryClient.setQueryData(meetingQueries.latest("workspace").queryKey, page([meetingSummary()]));
  queryClient.setQueryData(accessQueries.detail("meeting").queryKey, {
    access_mode: "workspace",
    member_ids: [],
  });
  const wrapper = ({ children }: { children: ReactNode }) => (
    <TestProviders queryClient={queryClient}>{children}</TestProviders>
  );
  return { queryClient, wrapper };
}

async function restrictMeeting() {
  server.use(
    http.put("/api/v1/meetings/{meeting_id}/access", ({ response }) =>
      response(200).json(RESTRICTED),
    ),
  );
  const { queryClient, wrapper } = seedCaches();
  const { result } = renderHook(() => useSetMeetingAccess("meeting", "workspace"), { wrapper });
  await result.current.mutateAsync(RESTRICTED);
  return queryClient;
}

test("a meeting's access sits under its detail key", () => {
  // Act
  const key = accessQueries.detail("meeting").queryKey;

  // Assert
  expect(key.slice(0, 3)).toEqual(meetingQueries.detail("meeting").queryKey);
});

test("changing access stores the server's copy of the setting", async () => {
  // Act
  const queryClient = await restrictMeeting();

  // Assert
  expect(queryClient.getQueryData(accessQueries.detail("meeting").queryKey)).toEqual(RESTRICTED);
});

test("changing access marks its workspace's meetings for a refetch", async () => {
  // Act
  const queryClient = await restrictMeeting();

  // Assert
  expect(
    queryClient.getQueryState(meetingQueries.latest("workspace").queryKey)?.isInvalidated,
  ).toBe(true);
});

test("a refused access change keeps the old setting", async () => {
  // Arrange
  server.use(
    http.put("/api/v1/meetings/{meeting_id}/access", ({ response }) =>
      response(403).json(errorBody("INSUFFICIENT_ROLE", "Only a Moderator or Owner can do that")),
    ),
  );
  const { queryClient, wrapper } = seedCaches();
  const { result } = renderHook(() => useSetMeetingAccess("meeting", "workspace"), { wrapper });

  // Act
  await expect(result.current.mutateAsync(RESTRICTED)).rejects.toThrow();

  // Assert
  expect(queryClient.getQueryData(accessQueries.detail("meeting").queryKey)).toEqual({
    access_mode: "workspace",
    member_ids: [],
  });
});
