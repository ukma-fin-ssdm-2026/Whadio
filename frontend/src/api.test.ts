import { describe, expect, test, vi } from "vitest";
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

test("transcript downloads default to current Markdown with timestamps", () => {
  // Act
  const url = api.transcriptExportUrl("meeting");

  // Assert
  expect(url).toBe(
    "/api/v1/meetings/meeting/transcript/export?format=markdown&version=current&timestamps=true",
  );
});

test.for(
  (["current", "original"] as const).flatMap((version) =>
    [true, false].map((timestamps) => ({ version, timestamps })),
  ),
)("Markdown download selects $version with timestamps=$timestamps", ({ version, timestamps }) => {
  // Act
  const url = api.transcriptExportUrl("meeting", { version, timestamps });

  // Assert
  expect(url).toBe(
    `/api/v1/meetings/meeting/transcript/export?format=markdown&version=${version}&timestamps=${timestamps}`,
  );
});

test.for(["current", "original"] as const)(
  "WebVTT download selects %s and retains mandatory timing",
  (version) => {
    // Act
    const url = api.transcriptExportUrl("meeting", { format: "vtt", version, timestamps: false });

    // Assert
    expect(url).toBe(`/api/v1/meetings/meeting/transcript/export?format=vtt&version=${version}`);
  },
);

test("transcript download encodes the meeting identifier", () => {
  // Act
  const url = api.transcriptExportUrl("meeting/other?query=yes");

  // Assert
  expect(url.split("/transcript/")[0]).toBe("/api/v1/meetings/meeting%2Fother%3Fquery%3Dyes");
});

test("notes download uses the current notes endpoint and encodes the meeting identifier", () => {
  // Act
  const url = api.notesExportUrl("meeting/other?query=yes");

  // Assert
  expect(url).toBe("/api/v1/meetings/meeting%2Fother%3Fquery%3Dyes/notes/export");
});

test("downloads from a configured origin with a trailing slash have no double slash", async () => {
  // Arrange
  vi.stubEnv("VITE_API_ORIGIN", "https://example.com/whadio/");
  vi.resetModules();
  const { api: configuredApi } = await import("./api");
  vi.unstubAllEnvs();

  // Act
  const url = configuredApi.notesExportUrl("meeting");

  // Assert
  expect(url).toBe("https://example.com/whadio/api/v1/meetings/meeting/notes/export");
});
