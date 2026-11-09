import { screen, waitFor } from "@testing-library/react";
import type { UserEvent } from "@testing-library/user-event";
import { expect, test } from "vitest";
import type { RevisionInput } from "@/shared/api/types";
import { errorBody, transcriptRead } from "@/shared/testing/fixtures";
import { renderWithProviders } from "@/shared/testing/render";
import { http, server } from "@/shared/testing/server";
import { TranscriptPanel } from "./TranscriptPanel";

const BASE = transcriptRead({
  speakers: [{ id: "speaker", display_name: "Speaker 1", is_unnamed: true }],
  segments: [
    {
      id: "one",
      speaker_id: "speaker",
      start_seconds: 65,
      end_seconds: 70,
      text: "We ship what audio on Friday",
    },
    { id: "two", speaker_id: "speaker", start_seconds: 75, end_seconds: 80, text: "Next steps" },
  ],
});

const SAVED = transcriptRead({
  revision: { ...BASE.revision, id: "edited", revision_type: "edited" },
  is_edited: true,
});

function captureEdits() {
  const edits: RevisionInput[] = [];
  server.use(
    http.post(
      "/api/v1/meetings/{meeting_id}/transcript/revisions",
      async ({ request, response }) => {
        edits.push(await request.json());
        return response(201).json(SAVED);
      },
    ),
  );
  return edits;
}

function refuseEdits(status: 404 | 409, code: "NOT_FOUND" | "STALE_REVISION") {
  server.use(
    http.post("/api/v1/meetings/{meeting_id}/transcript/revisions", ({ response }) =>
      response(status).json(errorBody(code, "Refused by the server")),
    ),
  );
}

async function startEditing(transcript = BASE) {
  const view = renderWithProviders(
    <TranscriptPanel
      meeting={{ id: "meeting", state: "processed" }}
      transcript={transcript}
      missing={false}
      loading={false}
      failed={false}
      query=""
      onQuery={() => {}}
      onRevision={() => {}}
      onShowCurrent={() => {}}
      onUnsavedChange={() => {}}
    />,
  );
  await view.user.click(screen.getByRole("button", { name: "Edit transcript" }));
  return view;
}

function refuseName(message: string) {
  server.use(
    http.post("/api/v1/meetings/{meeting_id}/transcript/revisions", ({ response }) =>
      response(422).json({
        error: {
          code: "VALIDATION_ERROR",
          message: "Request contains invalid fields",
          details: [{ field: "speakers.0.display_name", message }],
          request_id: "request",
        },
      }),
    ),
  );
}

const segmentButton = (time: string) =>
  screen.getByRole("button", { name: new RegExp(`^Edit text at ${time}`) });

const speakerField = (name: string) => screen.getByRole("textbox", { name });

async function rename(user: UserEvent, from: string, to: string) {
  await user.clear(speakerField(from));
  if (to) await user.type(speakerField(from), to);
}

async function correct(user: UserEvent, time: string, text: string) {
  await user.click(segmentButton(time));
  const field = screen.getByLabelText(`Text at ${time}`);
  await user.clear(field);
  if (text) await user.type(field, text);
  await user.tab();
}

async function save(user: UserEvent) {
  await user.click(screen.getByRole("button", { name: "Save" }));
}

test("editing hides the switch to the original", async () => {
  // Act
  await startEditing({ ...BASE, is_edited: true });

  // Assert
  expect(
    screen.queryByRole("button", { name: "View original transcript" }),
  ).not.toBeInTheDocument();
});

test("a correction is saved as a new revision of the shown one", async () => {
  // Arrange
  const edits = captureEdits();
  const { user } = await startEditing();
  await correct(user, "01:05", "We ship Whadio on Friday");

  // Act
  await save(user);

  // Assert
  await waitFor(() =>
    expect(edits).toEqual([
      { base_revision_id: "revision", segments: [{ id: "one", text: "We ship Whadio on Friday" }] },
    ]),
  );
});

test("several corrections are saved together in one revision", async () => {
  // Arrange
  const edits = captureEdits();
  const { user } = await startEditing();
  await correct(user, "01:05", "We ship Whadio on Friday");
  await correct(user, "01:15", "Next steps agreed");

  // Act
  await save(user);

  // Assert
  await waitFor(() =>
    expect(edits).toEqual([
      {
        base_revision_id: "revision",
        segments: [
          { id: "one", text: "We ship Whadio on Friday" },
          { id: "two", text: "Next steps agreed" },
        ],
      },
    ]),
  );
});

test("a cleared segment is saved with no text", async () => {
  // Arrange
  const edits = captureEdits();
  const { user } = await startEditing();
  await correct(user, "01:05", "");

  // Act
  await save(user);

  // Assert
  await waitFor(() => expect(edits[0]?.segments).toEqual([{ id: "one", text: "" }]));
});

test("a cleared segment says it has no text", async () => {
  // Arrange
  const { user } = await startEditing();

  // Act
  await correct(user, "01:05", "");

  // Assert
  expect(segmentButton("01:05")).toHaveTextContent("No text");
});

test("the bar counts the corrected segments", async () => {
  // Arrange
  const { user } = await startEditing();

  // Act
  await correct(user, "01:05", "We ship Whadio on Friday");

  // Assert
  expect(screen.getByRole("status")).toHaveTextContent(/^1 unsaved change\./);
});

test("a corrected segment is marked as changed", async () => {
  // Arrange
  const { user } = await startEditing();

  // Act
  await correct(user, "01:05", "We ship Whadio on Friday");

  // Assert
  expect(screen.getAllByText("Changed")).toHaveLength(1);
});

test("text typed back to what it was is no change", async () => {
  // Arrange
  const { user } = await startEditing();

  // Act
  await correct(user, "01:05", "We ship what audio on Friday");

  // Assert
  expect(screen.getByRole("button", { name: "Save" })).toBeDisabled();
});

test("Escape puts the segment's text back", async () => {
  // Arrange
  const { user } = await startEditing();
  await user.click(segmentButton("01:05"));
  await user.type(screen.getByLabelText("Text at 01:05"), " in full");

  // Act
  await user.keyboard("{Escape}");

  // Assert
  expect(segmentButton("01:05")).toHaveTextContent(/^We ship what audio on Friday$/);
});

test("Escape returns the focus to the segment", async () => {
  // Arrange
  const { user } = await startEditing();
  await user.click(segmentButton("01:05"));

  // Act
  await user.keyboard("{Escape}");

  // Assert
  expect(segmentButton("01:05")).toHaveFocus();
});

test("discarding shows the saved text again", async () => {
  // Arrange
  const { user } = await startEditing();
  await correct(user, "01:05", "We ship Whadio on Friday");

  // Act
  await user.click(screen.getByRole("button", { name: "Discard changes" }));

  // Assert
  expect(screen.getByText("We ship what audio on Friday")).toBeInTheDocument();
});

test("a saved correction says that the original is kept", async () => {
  // Arrange
  captureEdits();
  const { user } = await startEditing();
  await correct(user, "01:05", "We ship Whadio on Friday");

  // Act
  await save(user);

  // Assert
  expect(await screen.findByRole("alert")).toHaveTextContent(
    "Transcript saved. The original stays available.",
  );
});

test("a saved correction closes the editor", async () => {
  // Arrange
  captureEdits();
  const { user } = await startEditing();
  await correct(user, "01:05", "We ship Whadio on Friday");

  // Act
  await save(user);

  // Assert
  expect(await screen.findByRole("button", { name: "Edit transcript" })).toBeInTheDocument();
});

test("a stale revision says that someone else edited the transcript", async () => {
  // Arrange
  refuseEdits(409, "STALE_REVISION");
  const { user } = await startEditing();
  await correct(user, "01:05", "We ship Whadio on Friday");

  // Act
  await save(user);

  // Assert
  expect(await screen.findByRole("alert")).toHaveTextContent(
    "Someone else edited this transcript, so it was reloaded. Your 1 change was not saved.",
  );
});

test("a stale revision keeps no unsaved change", async () => {
  // Arrange
  refuseEdits(409, "STALE_REVISION");
  const { user } = await startEditing();
  await correct(user, "01:05", "We ship Whadio on Friday");

  // Act
  await save(user);

  // Assert
  await waitFor(() => expect(screen.queryByText("Changed")).not.toBeInTheDocument());
});

test("a failed save shows the server's message", async () => {
  // Arrange
  refuseEdits(404, "NOT_FOUND");
  const { user } = await startEditing();
  await correct(user, "01:05", "We ship Whadio on Friday");

  // Act
  await save(user);

  // Assert
  expect(await screen.findByRole("alert")).toHaveTextContent("Refused by the server");
});

test("a failed save keeps the corrections for another try", async () => {
  // Arrange
  refuseEdits(404, "NOT_FOUND");
  const { user } = await startEditing();
  await correct(user, "01:05", "We ship Whadio on Friday");

  // Act
  await save(user);
  await screen.findByRole("alert");

  // Assert
  expect(segmentButton("01:05")).toHaveTextContent("We ship Whadio on Friday");
});

test("a rename is saved by the speaker's id in the shown revision", async () => {
  // Arrange
  const edits = captureEdits();
  const { user } = await startEditing();
  await rename(user, "Speaker 1", "Olena Bondar");

  // Act
  await save(user);

  // Assert
  await waitFor(() =>
    expect(edits).toEqual([
      { base_revision_id: "revision", speakers: [{ id: "speaker", display_name: "Olena Bondar" }] },
    ]),
  );
});

test("a correction and a rename are saved together in one revision", async () => {
  // Arrange
  const edits = captureEdits();
  const { user } = await startEditing();
  await correct(user, "01:05", "We ship Whadio on Friday");
  await rename(user, "Speaker 1", "Olena Bondar");

  // Act
  await save(user);

  // Assert
  await waitFor(() =>
    expect(edits).toEqual([
      {
        base_revision_id: "revision",
        segments: [{ id: "one", text: "We ship Whadio on Friday" }],
        speakers: [{ id: "speaker", display_name: "Olena Bondar" }],
      },
    ]),
  );
});

test("a renamed speaker labels every one of their segments", async () => {
  // Arrange
  const { user } = await startEditing();

  // Act
  await rename(user, "Speaker 1", "Olena Bondar");

  // Assert
  expect(screen.getAllByText("Olena Bondar")).toHaveLength(2);
});

test("a speaker's name says how many segments it applies to", async () => {
  // Act
  await startEditing();

  // Assert
  expect(speakerField("Speaker 1")).toHaveAccessibleDescription("Applies to 2 segments");
});

test("an emptied speaker name says to enter one", async () => {
  // Arrange
  const { user } = await startEditing();
  await rename(user, "Speaker 1", "");

  // Act
  await save(user);

  // Assert
  expect(await screen.findByText("Enter a name")).toBeInTheDocument();
});

test("an emptied speaker name sends nothing", async () => {
  // Arrange
  const edits = captureEdits();
  const { user } = await startEditing();
  await rename(user, "Speaker 1", "");

  // Act
  await save(user);
  await screen.findByText("Enter a name");

  // Assert
  expect(edits).toEqual([]);
});

test("a name the server refuses is explained on the field of that speaker", async () => {
  // Arrange
  refuseName("Name contains no visible character");
  const { user } = await startEditing({
    ...BASE,
    speakers: [...BASE.speakers, { id: "other", display_name: "Speaker 2", is_unnamed: true }],
  });
  await rename(user, "Speaker 2", "Taras Melnyk");

  // Act
  await save(user);

  // Assert
  await waitFor(() =>
    expect(speakerField("Speaker 2")).toHaveAccessibleDescription(
      "Name contains no visible character",
    ),
  );
});
