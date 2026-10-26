import assert from "node:assert/strict";
import test from "node:test";
import { api } from "./api.js";

test("transcript downloads default to current Markdown with timestamps", () => {
  assert.equal(
    api.transcriptExportUrl("meeting"),
    "/api/v1/meetings/meeting/transcript/export?format=markdown&version=current&timestamps=true",
  );
});

for (const version of ["current", "original"]) {
  for (const timestamps of [true, false]) {
    test(`Markdown download selects ${version} with timestamps=${timestamps}`, () => {
      assert.equal(
        api.transcriptExportUrl("meeting", { version, timestamps }),
        `/api/v1/meetings/meeting/transcript/export?format=markdown&version=${version}&timestamps=${timestamps}`,
      );
    });
  }
  test(`WebVTT download selects ${version} and retains mandatory timing`, () => {
    assert.equal(
      api.transcriptExportUrl("meeting", { format: "vtt", version, timestamps: false }),
      `/api/v1/meetings/meeting/transcript/export?format=vtt&version=${version}`,
    );
  });
}

test("transcript download encodes the meeting identifier", () => {
  assert.equal(
    api.transcriptExportUrl("meeting/other?query=yes").split("/transcript/")[0],
    "/api/v1/meetings/meeting%2Fother%3Fquery%3Dyes",
  );
});

test("notes download uses the current notes endpoint and encodes the meeting identifier", () => {
  assert.equal(
    api.notesExportUrl("meeting/other?query=yes"),
    "/api/v1/meetings/meeting%2Fother%3Fquery%3Dyes/notes/export",
  );
});
