import {
  infiniteQueryOptions,
  queryOptions,
  useMutation,
  useQueryClient,
} from "@tanstack/react-query";
import { apiClient } from "@/shared/api/client";
import type { Schemas } from "@/shared/api/types";
import { expectNoContent, unwrap } from "@/shared/api/unwrap";
import { detailKey } from "./keys";

export type Share = Schemas["ShareRead"];
export type AccessRequest = Schemas["RequestRead"];

const FIRST_PAGE = "";

const sharesKey = (meetingId: string) => [...detailKey(meetingId), "shares"] as const;
const requestsKey = (shareId: string) => ["shares", shareId, "access-requests"] as const;
const receivedKey = ["shares", "received"] as const;

export const shareQueries = {
  list: (meetingId: string) =>
    infiniteQueryOptions({
      queryKey: sharesKey(meetingId),
      queryFn: ({ pageParam, signal }) =>
        unwrap(
          apiClient.GET("/api/v1/meetings/{meeting_id}/shares", {
            params: {
              path: { meeting_id: meetingId },
              query: { limit: 100, cursor: pageParam || null },
            },
            signal,
          }),
        ),
      initialPageParam: FIRST_PAGE,
      getNextPageParam: ({ pagination }) => (pagination.has_more ? pagination.next_cursor : null),
      select: ({ pages }) => pages.flatMap((page) => page.items),
    }),
  requests: (shareId: string) =>
    infiniteQueryOptions({
      queryKey: requestsKey(shareId),
      queryFn: ({ pageParam, signal }) =>
        unwrap(
          apiClient.GET("/api/v1/shares/{share_id}/access-requests", {
            params: {
              path: { share_id: shareId },
              query: { limit: 100, cursor: pageParam || null },
            },
            signal,
          }),
        ),
      initialPageParam: FIRST_PAGE,
      getNextPageParam: ({ pagination }) => (pagination.has_more ? pagination.next_cursor : null),
      select: ({ pages }) => pages.flatMap((page) => page.items),
    }),
  received: () =>
    infiniteQueryOptions({
      queryKey: receivedKey,
      queryFn: ({ pageParam, signal }) =>
        unwrap(
          apiClient.GET("/api/v1/users/me/shares", {
            params: { query: { limit: 100, cursor: pageParam || null } },
            signal,
          }),
        ),
      initialPageParam: FIRST_PAGE,
      getNextPageParam: ({ pagination }) => (pagination.has_more ? pagination.next_cursor : null),
      select: ({ pages }) => pages.flatMap((page) => page.items),
    }),
  transcript: (shareId: string) =>
    queryOptions({
      queryKey: [...receivedKey, shareId, "transcript"],
      queryFn: ({ signal }) =>
        unwrap(
          apiClient.GET("/api/v1/shares/{share_id}/transcript", {
            params: { path: { share_id: shareId } },
            signal,
          }),
        ),
      retry: false,
    }),
  notes: (shareId: string) =>
    queryOptions({
      queryKey: [...receivedKey, shareId, "notes"],
      queryFn: ({ signal }) =>
        unwrap(
          apiClient.GET("/api/v1/shares/{share_id}/notes", {
            params: { path: { share_id: shareId }, query: { limit: 1 } },
            signal,
          }),
        ),
      select: (page) => page.items[0] ?? null,
      retry: false,
    }),
};

export function requestShareAccess(shareId: string, token: string) {
  return unwrap(
    apiClient.POST("/api/v1/shares/{share_id}/access-requests", {
      params: { path: { share_id: shareId } },
      body: { token },
    }),
  );
}

export function useDecideRequest(shareId: string) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({ requestId, approve }: { requestId: string; approve: boolean }) =>
      unwrap(
        approve
          ? apiClient.POST("/api/v1/share-access-requests/{request_id}/approve", {
              params: { path: { request_id: requestId } },
            })
          : apiClient.POST("/api/v1/share-access-requests/{request_id}/decline", {
              params: { path: { request_id: requestId } },
            }),
      ),
    onSettled: () => queryClient.invalidateQueries({ queryKey: requestsKey(shareId) }),
  });
}

export function useCreateShare(meetingId: string) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (share: Schemas["ShareInput"]) =>
      unwrap(
        apiClient.POST("/api/v1/meetings/{meeting_id}/shares", {
          params: { path: { meeting_id: meetingId } },
          body: share,
        }),
      ),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: sharesKey(meetingId) }),
  });
}

export function useRevokeShare(meetingId: string) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (shareId: string) =>
      expectNoContent(
        apiClient.DELETE("/api/v1/shares/{share_id}", {
          params: { path: { share_id: shareId } },
        }),
      ),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: sharesKey(meetingId) }),
  });
}
