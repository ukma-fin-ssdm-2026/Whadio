import { describe, expect, test } from "vitest";
import { api } from "./api";
import type { Schemas } from "./shared/api/types";
import { http, server } from "./shared/testing/server";

const CREATED_AT = "2026-10-25T10:00:00Z";

const TRANSCRIPT: Schemas["TranscriptRead"] = {
  meeting_id: "meeting",
  language: "uk",
  model_name: "whisper",
  revision: {
    id: "revision",
    revision_type: "original",
    created_at: CREATED_AT,
    edited_by_user_id: null,
    is_current: true,
  },
  original_revision_id: "revision",
  is_edited: false,
  has_unnamed_speakers: false,
  speakers: [],
  segments: [],
};

function captureTranscriptQuery() {
  const searches: string[] = [];
  server.use(
    http.get("/api/v1/meetings/{meeting_id}/transcript", ({ request, response }) => {
      searches.push(new URL(request.url).search);
      return response(200).json(TRANSCRIPT);
    }),
  );
  return searches;
}

describe("requests", () => {
  test("transcript request names the requested revision", async () => {
    // Arrange
    const searches = captureTranscriptQuery();

    // Act
    await api.getTranscript("meeting", "revision");

    // Assert
    expect(searches).toEqual(["?revision_id=revision"]);
  });

  test("current transcript request sends no revision", async () => {
    // Arrange
    const searches = captureTranscriptQuery();

    // Act
    await api.getTranscript("meeting");

    // Assert
    expect(searches).toEqual([""]);
  });
});
