import { describe, expect, test, vi } from "vitest";
import { api, recordingForm } from "./api";
import type { Schemas } from "./shared/api/types";
import { http, server } from "./shared/testing/server";

const CREATED_AT = "2026-10-25T10:00:00Z";

const SESSION: Schemas["SessionRead"] = {
  kind: "browser",
  expires_at: CREATED_AT,
  user: {
    id: "member",
    email: "member@example.com",
    name: "Demo Member",
    is_administrator: false,
    created_at: CREATED_AT,
  },
};

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

const MCP_KEY: Schemas["McpKeyCreated"] = {
  id: "key",
  created_at: CREATED_AT,
  expires_at: null,
  revoked_at: null,
  is_active: true,
  secret: "whadio_mcp_secret",
};

function captureSignIn() {
  const bodies: unknown[] = [];
  server.use(
    http.post("/api/v1/sessions", async ({ request, response }) => {
      bodies.push(await request.json());
      return response(201).json(SESSION);
    }),
  );
  return bodies;
}

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

function captureMcpKeyCreate() {
  const bodies: unknown[] = [];
  server.use(
    http.post("/api/v1/users/me/mcp-keys", async ({ request, response }) => {
      bodies.push(await request.json());
      return response(201).json(MCP_KEY);
    }),
  );
  return bodies;
}

const formFields = (form: FormData) =>
  [...form.entries()].map(([key, value]) => [key, typeof value === "string" ? value : value.name]);

describe("recording upload form", () => {
  test("carries the file and the trimmed name", () => {
    // Arrange
    const file = new File(["RIFF"], "standup.wav", { type: "audio/wav" });

    // Act
    const form = recordingForm({ file, name: "  Standup  " });

    // Assert
    expect(formFields(form)).toEqual([
      ["file", "standup.wav"],
      ["name", "Standup"],
    ]);
  });

  test("leaves out a blank name", () => {
    // Arrange
    const file = new File(["RIFF"], "standup.wav", { type: "audio/wav" });

    // Act
    const form = recordingForm({ file, name: "   " });

    // Assert
    expect(formFields(form)).toEqual([["file", "standup.wav"]]);
  });
});

describe("requests", () => {
  test("sign-in sends the credentials for a browser session", async () => {
    // Arrange
    const bodies = captureSignIn();

    // Act
    await api.signIn("member@example.com", "test-password");

    // Assert
    expect(bodies).toEqual([
      { email: "member@example.com", password: "test-password", kind: "browser" },
    ]);
  });

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

  test("MCP key that never expires is created with a null expiry", async () => {
    // Arrange
    const bodies = captureMcpKeyCreate();

    // Act
    await api.createMcpKey(null);

    // Assert
    expect(bodies).toEqual([{ expires_in_days: null }]);
  });

  test("MCP key is created with the chosen lifetime in days", async () => {
    // Arrange
    const bodies = captureMcpKeyCreate();

    // Act
    await api.createMcpKey(30);

    // Assert
    expect(bodies).toEqual([{ expires_in_days: 30 }]);
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
