import { expect, test } from "vitest";
import { transcriptRead } from "@/shared/testing/fixtures";
import { countChanges, draftOf, revisionInput, transcriptDraft } from "./transcript-draft";

const BASE = transcriptRead({
  speakers: [
    { id: "olena", display_name: "Speaker 1", is_unnamed: true },
    { id: "taras", display_name: "Speaker 2", is_unnamed: true },
  ],
  segments: [
    {
      id: "one",
      speaker_id: "olena",
      start_seconds: 0,
      end_seconds: 5,
      text: "We ship what audio on Friday",
    },
    { id: "two", speaker_id: "taras", start_seconds: 5, end_seconds: 9, text: "Next steps" },
  ],
});

const UNNAMED = [{ name: "Speaker 1" }, { name: "Speaker 2" }];
const NEXT = { text: "Next steps" };
const SAID = [{ text: "We ship what audio on Friday" }, NEXT];

const nameIssue = (name: string) =>
  transcriptDraft.safeParse({ speakers: [{ name }], segments: [] }).error?.issues[0]?.message;

test("an untouched draft asks for no revision", () => {
  // Act
  const input = revisionInput(BASE, draftOf(BASE));

  // Assert
  expect(input).toBeNull();
});

test("only the corrected segment is sent, by its id in the base revision", () => {
  // Arrange
  const draft = { speakers: UNNAMED, segments: [{ text: "We ship Whadio on Friday" }, NEXT] };

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
  const draft = { speakers: UNNAMED, segments: [{ text: "We ship what audio on Friday " }, NEXT] };

  // Act
  const input = revisionInput(BASE, draft);

  // Assert
  expect(input?.segments).toEqual([{ id: "one", text: "We ship what audio on Friday " }]);
});

test("only the renamed speaker is sent, trimmed, by its id in the base revision", () => {
  // Arrange
  const draft = { speakers: [{ name: " Olena Bondar " }, { name: "Speaker 2" }], segments: SAID };

  // Act
  const input = revisionInput(BASE, draft);

  // Assert
  expect(input).toEqual({
    base_revision_id: "revision",
    speakers: [{ id: "olena", display_name: "Olena Bondar" }],
  });
});

test("a name changed only in surrounding space is no rename", () => {
  // Arrange
  const draft = { speakers: [{ name: "Speaker 1 " }, { name: "Speaker 2" }], segments: SAID };

  // Act
  const input = revisionInput(BASE, draft);

  // Assert
  expect(input).toBeNull();
});

test("a blank speaker name is refused", () => {
  // Act
  const issue = nameIssue("   ");

  // Assert
  expect(issue).toBe("Enter a name");
});

test("a speaker name over 200 characters is refused", () => {
  // Act
  const issue = nameIssue("a".repeat(201));

  // Assert
  expect(issue).toBe("Use 200 characters or fewer");
});

test("a name of 200 characters outside the basic plane fits the limit", () => {
  // Act
  const issue = nameIssue("😀".repeat(200));

  // Assert
  expect(issue).toBeUndefined();
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
    speakers: [{ id: "olena", display_name: "Olena" }],
  };

  // Act
  const changes = countChanges(input);

  // Assert
  expect(changes).toBe(2);
});
