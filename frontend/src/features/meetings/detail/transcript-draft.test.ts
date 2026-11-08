import { expect, test } from "vitest";
import { transcriptRead } from "@/shared/testing/fixtures";
import { countChanges, draftOf, revisionInput } from "./transcript-draft";

const BASE = transcriptRead({
  segments: [
    {
      id: "one",
      speaker_id: null,
      start_seconds: 0,
      end_seconds: 5,
      text: "We ship what audio on Friday",
    },
    { id: "two", speaker_id: null, start_seconds: 5, end_seconds: 9, text: "Next steps" },
  ],
});

test("an untouched draft asks for no revision", () => {
  // Act
  const input = revisionInput(BASE, draftOf(BASE));

  // Assert
  expect(input).toBeNull();
});

test("only the corrected segment is sent, by its id in the base revision", () => {
  // Arrange
  const draft = { segments: [{ text: "We ship Whadio on Friday" }, { text: "Next steps" }] };

  // Act
  const input = revisionInput(BASE, draft);

  // Assert
  expect(input).toEqual({
    base_revision_id: "revision",
    segments: [{ id: "one", text: "We ship Whadio on Friday" }],
  });
});

test("text that differs only in surrounding space is a correction", () => {
  // Arrange
  const draft = { segments: [{ text: "We ship what audio on Friday " }, { text: "Next steps" }] };

  // Act
  const input = revisionInput(BASE, draft);

  // Assert
  expect(input?.segments).toEqual([{ id: "one", text: "We ship what audio on Friday " }]);
});

test("no revision counts no change", () => {
  // Act
  const changes = countChanges(null);

  // Assert
  expect(changes).toBe(0);
});

test("text corrections and speaker renames count together", () => {
  // Arrange
  const input = {
    base_revision_id: "revision",
    segments: [{ id: "one", text: "We ship Whadio on Friday" }],
    speakers: [{ id: "speaker", display_name: "Olena" }],
  };

  // Act
  const changes = countChanges(input);

  // Assert
  expect(changes).toBe(2);
});
