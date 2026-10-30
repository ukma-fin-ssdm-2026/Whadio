import { fireEvent, screen, waitFor } from "@testing-library/react";
import type { ComponentProps } from "react";
import { expect, test } from "vitest";
import { ExportMenu } from "@/features/export/components/ExportMenu";
import type { Schemas } from "@/shared/api/types";
import { errorBody, meetingRead, noteRead, page, transcriptRead } from "@/shared/testing/fixtures";
import { createTestQueryClient, renderWithProviders } from "@/shared/testing/render";
import { http, server } from "@/shared/testing/server";
import { meetingQueries } from "../api/meetings";
import { mapMeeting } from "../model";
import { MeetingDetail } from "./MeetingDetail";

function meeting(changes: Partial<Schemas["MeetingRead"]> = {}) {
  return mapMeeting(meetingRead(changes));
}

function revision(revisionId: string): Schemas["TranscriptRead"] {
  return transcriptRead({
    revision: {
      ...transcriptRead().revision,
      id: revisionId,
      revision_type: revisionId === "original" ? "original" : "edited",
    },
    original_revision_id: "original",
    is_edited: true,
  });
}

function serveContent() {
  const requests: string[] = [];
  server.use(
    http.get("/api/v1/meetings/{meeting_id}/notes", ({ response }) => {
      requests.push("notes");
      return response(200).json(page([noteRead()]));
    }),
    http.get("/api/v1/meetings/{meeting_id}/transcript", ({ request, response }) => {
      const revisionId = new URL(request.url).searchParams.get("revision_id");
      requests.push(revisionId ? `transcript ${revisionId}` : "transcript");
      return response(200).json(revision(revisionId ?? "edited"));
    }),
    http.get("/api/v1/meetings/{meeting_id}/recording", ({ response }) => {
      requests.push("recording");
      return response(200).json({ url: "", expires_at: "2026-10-25T10:05:00Z" });
    }),
  );
  return requests;
}

function serveSpokenTranscript() {
  const segment = { id: "one", speaker_id: null, start_seconds: 0, end_seconds: 5 };
  server.use(
    http.get("/api/v1/meetings/{meeting_id}/transcript", ({ response }) =>
      response(200).json(transcriptRead({ segments: [{ ...segment, text: "Budget agreed" }] })),
    ),
  );
}

function refuseTranscript() {
  serveContent();
  server.use(
    http.get("/api/v1/meetings/{meeting_id}/transcript", ({ response }) =>
      response(409).json(errorBody("NOT_TRANSCRIBED", "Not transcribed")),
    ),
  );
}

function detail(changes: Partial<ComponentProps<typeof MeetingDetail>> = {}) {
  const props = {
    meeting: meeting(),
    revisionId: null,
    tab: "notes" as const,
    transcriptQuery: "",
    onTab: () => {},
    onTranscriptQuery: () => {},
    onRevision: () => {},
    ...changes,
  };
  return (
    <MeetingDetail
      {...props}
      renderExport={({ transcript, notes }) => (
        <ExportMenu
          meetingId={props.meeting.id}
          tab={props.tab}
          transcript={transcript}
          notes={notes}
        />
      )}
    />
  );
}

function renderDetail(changes: Partial<ComponentProps<typeof MeetingDetail>> = {}) {
  return renderWithProviders(detail(changes), createTestQueryClient());
}

async function openTranscriptDownloads() {
  const view = renderDetail({ tab: "transcript" });
  await view.user.click(await screen.findByRole("button", { name: "Download transcript" }));
  return view;
}

const failed = () => meeting({ processing_state: "failed", failure_reason: "notes_failed" });
const processing = () => meeting({ processing_state: "processing" });
const transcribing = (state: "failed" | "processing") =>
  state === "failed" ? failed() : processing();
const interactive = 'button, a[href], input, select, [role="button"], [tabindex="0"]';

test("meeting header has no workspace access control", () => {
  // Arrange
  serveContent();

  // Act
  renderDetail();

  // Assert
  expect(screen.queryByLabelText("Workspace access")).not.toBeInTheDocument();
});

test("meeting header names the source as text beside the date", () => {
  // Arrange
  serveContent();

  // Act
  renderDetail();

  // Assert
  expect(screen.getByText(/^\w{3} \d+, \d{4}.* · Google Meet$/)).toBeInTheDocument();
});

test.for(["notes", "transcript", "recording"] as const)(
  "%s tab has the meeting title as its only first-level heading",
  async (tab) => {
    // Arrange
    serveContent();

    // Act
    renderDetail({ tab });
    await screen.findByRole("tabpanel");

    // Assert
    expect(screen.getAllByRole("heading", { level: 1 }).map((h) => h.textContent)).toEqual([
      "Weekly sync",
    ]);
  },
);

test("tab panel is labelled by the selected tab", () => {
  // Arrange
  serveContent();

  // Act
  renderDetail({ tab: "transcript" });

  // Assert
  expect(screen.getByRole("tabpanel")).toHaveAccessibleName("Transcript");
});

test("queued meeting notes panel is headed Queued", () => {
  // Arrange
  const { container } = renderDetail({ meeting: meeting({ processing_state: "queued" }) });

  // Act
  const heading = container.querySelector(".processing-panel .MuiTypography-subtitle1");

  // Assert
  expect(heading).toHaveTextContent(/^Queued$/);
});

test("in-progress notes panel offers no control", () => {
  // Arrange
  const { container } = renderDetail({ meeting: meeting({ processing_state: "queued" }) });

  // Act
  const controls = container.querySelectorAll(`.processing-panel :is(${interactive})`);

  // Assert
  expect(controls).toHaveLength(0);
});

test("in-progress notes panel says the transcript comes first, on its own tab", () => {
  // Act
  renderDetail({ meeting: meeting({ processing_state: "queued" }) });

  // Assert
  expect(
    screen.getByText(
      "Notes appear here when processing finishes. The transcript appears in its tab as soon as it is ready.",
    ),
  ).toBeInTheDocument();
});

test("a processed meeting loads its notes", async () => {
  // Arrange
  serveContent();

  // Act
  renderDetail();

  // Assert
  expect(await screen.findByText("Saved notes")).toBeInTheDocument();
});

test("notes render as Markdown, without their markup characters", async () => {
  // Arrange
  serveContent();
  server.use(
    http.get("/api/v1/meetings/{meeting_id}/notes", ({ response }) =>
      response(200).json(page([noteRead({ content: "## Decisions\n\n- Ship it" })])),
    ),
  );

  // Act
  renderDetail();

  // Assert
  expect(await screen.findByRole("heading", { name: "Decisions" })).toHaveTextContent(
    /^Decisions$/,
  );
});

test("a failed meeting explains its failure on the notes tab", () => {
  // Arrange
  serveContent();

  // Act
  renderDetail({ meeting: failed() });

  // Assert
  expect(screen.getByRole("alert")).toHaveTextContent(
    /^Notes could not be written for this meeting\.$/,
  );
});

test("a failed meeting with an unknown reason never shows the code", () => {
  // Arrange
  serveContent();

  // Act
  renderDetail({
    meeting: meeting({ processing_state: "failed", failure_reason: "disk_full" }),
  });

  // Assert
  expect(screen.getByRole("alert")).toHaveTextContent("Processing failed for this meeting.");
});

const WITHOUT_NOTES = ["failed", "processing"] as const;

test.for(WITHOUT_NOTES)("a %s meeting with a transcript shows it", async (state) => {
  // Arrange
  serveContent();
  serveSpokenTranscript();

  // Act
  renderDetail({ meeting: transcribing(state), tab: "transcript" });

  // Assert
  expect(await screen.findByText("Budget agreed")).toBeInTheDocument();
});

test.for(WITHOUT_NOTES)(
  "a %s meeting offers the original of its edited transcript",
  async (state) => {
    // Arrange
    serveContent();

    // Act
    renderDetail({ meeting: transcribing(state), tab: "transcript" });

    // Assert
    expect(
      await screen.findByRole("button", { name: "View original transcript" }),
    ).toBeInTheDocument();
  },
);

test.for(WITHOUT_NOTES)("searching the transcript of a %s meeting filters it", async (state) => {
  // Arrange
  serveContent();
  serveSpokenTranscript();

  // Act
  renderDetail({ meeting: transcribing(state), tab: "transcript", transcriptQuery: "absent" });

  // Assert
  expect(await screen.findByText("No transcript matches your search.")).toBeInTheDocument();
});

test.for(WITHOUT_NOTES)("a %s meeting offers its transcript for download", async (state) => {
  // Arrange
  serveContent();

  // Act
  renderDetail({ meeting: transcribing(state), tab: "transcript" });

  // Assert
  expect(await screen.findByRole("button", { name: "Download transcript" })).toBeInTheDocument();
});

test.for(WITHOUT_NOTES)(
  "the notes tab of a %s meeting loads the transcript but not the notes",
  async (state) => {
    // Arrange
    const requests = serveContent();

    // Act
    renderDetail({ meeting: transcribing(state) });
    await waitFor(() => expect(requests).toContain("transcript"));

    // Assert
    expect(requests).not.toContain("notes");
  },
);

test("a revision is requested by its identifier", async () => {
  // Arrange
  const requests = serveContent();

  // Act
  renderDetail({ tab: "transcript", revisionId: "original" });

  // Assert
  await waitFor(() => expect(requests).toContain("transcript original"));
});

test("the recording link waits for the recording tab", async () => {
  // Arrange
  const requests = serveContent();

  // Act
  renderDetail({ meeting: meeting({ recording_available: true }) });
  await screen.findByText("Saved notes");

  // Assert
  expect(requests).not.toContain("recording");
});

test("the recording tab requests the link of an available recording", async () => {
  // Arrange
  const requests = serveContent();

  // Act
  renderDetail({ meeting: meeting({ recording_available: true }), tab: "recording" });

  // Assert
  await waitFor(() => expect(requests).toContain("recording"));
});

async function watchRecordingLink(afterLoad: "recording" | "notes") {
  const requests = serveContent();
  const available = meeting({ recording_available: true });
  const view = renderDetail({ meeting: available, tab: "recording" });
  await waitFor(() => expect(requests).toContain("recording"));
  await waitFor(() =>
    expect(
      view.queryClient.getQueryData(meetingQueries.recording(available).queryKey),
    ).toBeDefined(),
  );
  view.rerender(detail({ meeting: available, tab: afterLoad }));
  return { ...view, requests, available };
}

test.for(["recording", "notes"] as const)(
  "a recording that goes away while the %s tab is open leaves no link in the cache",
  async (tab) => {
    // Arrange
    const { rerender, queryClient, available } = await watchRecordingLink(tab);

    // Act
    rerender(detail({ meeting: meeting({ recording_available: false }), tab }));

    // Assert
    expect(queryClient.getQueryData(meetingQueries.recording(available).queryKey)).toBeUndefined();
  },
);

test("reopening a meeting keeps the link of its available recording", async () => {
  // Arrange
  const { unmount, queryClient, available } = await watchRecordingLink("recording");
  unmount();

  // Act
  renderWithProviders(detail({ meeting: available, tab: "recording" }), queryClient);

  // Assert
  expect(queryClient.getQueryData(meetingQueries.recording(available).queryKey)).toBeDefined();
});

test("another meeting does not inherit the position of a failed recording", async () => {
  // Arrange
  serveContent();
  server.use(
    http.get("/api/v1/meetings/{meeting_id}/recording", ({ params, response }) =>
      response(200).json({
        url: `https://storage.example/${params.meeting_id}`,
        expires_at: "2026-10-25T10:05:00Z",
      }),
    ),
  );
  const { rerender } = renderDetail({
    meeting: meeting({ recording_available: true }),
    tab: "recording",
  });
  const failing = await screen.findByLabelText<HTMLVideoElement>("Weekly sync recording");
  failing.currentTime = 1800;
  fireEvent.error(failing);
  rerender(
    detail({ meeting: meeting({ id: "other", recording_available: true }), tab: "recording" }),
  );
  const next = await screen.findByLabelText<HTMLVideoElement>("Weekly sync recording");

  // Act
  fireEvent.loadedMetadata(next);

  // Assert
  expect(next.currentTime).toBe(0);
});

test("a recording that comes back asks for a new link", async () => {
  // Arrange
  const { rerender, requests, available } = await watchRecordingLink("recording");
  rerender(detail({ meeting: meeting({ recording_available: false }), tab: "recording" }));

  // Act
  rerender(detail({ meeting: available, tab: "recording" }));

  // Assert
  await waitFor(() => expect(requests.filter((item) => item === "recording")).toHaveLength(2));
});

test("a meeting with no transcript says so without an alert", async () => {
  // Arrange
  refuseTranscript();

  // Act
  renderDetail({ meeting: failed(), tab: "transcript" });
  await screen.findByText("This meeting has no transcript.");

  // Assert
  expect(screen.queryByRole("alert")).not.toBeInTheDocument();
});

async function watchUntranscribedMeeting() {
  refuseTranscript();
  const view = renderDetail({ meeting: processing(), tab: "transcript" });
  await screen.findByText("Transcript is not available yet.");
  return view;
}

test("a processing meeting with no transcript yet shows no alert", async () => {
  // Act
  await watchUntranscribedMeeting();

  // Assert
  expect(screen.queryByRole("alert")).not.toBeInTheDocument();
});

test("leaving processing never claims there is no transcript while it is asked for", async () => {
  // Arrange
  const { rerender } = await watchUntranscribedMeeting();

  // Act
  rerender(detail({ meeting: meeting(), tab: "transcript" }));

  // Assert
  expect(screen.getByText("Transcript is not available yet.")).toBeInTheDocument();
});

test.for([
  ["processed", meeting],
  ["failed", failed],
] as const)("a meeting that becomes %s shows its transcript at once", async ([, ended]) => {
  // Arrange
  const { rerender } = await watchUntranscribedMeeting();
  serveSpokenTranscript();

  // Act
  rerender(detail({ meeting: ended(), tab: "transcript" }));

  // Assert
  expect(await screen.findByText("Budget agreed")).toBeInTheDocument();
});

test("a meeting that fails in transcription ends up with no transcript", async () => {
  // Arrange
  const { rerender } = await watchUntranscribedMeeting();

  // Act
  rerender(detail({ meeting: failed(), tab: "transcript" }));

  // Assert
  expect(await screen.findByText("This meeting has no transcript.")).toBeInTheDocument();
});

test("a meeting sent back to the queue does not ask for its transcript", async () => {
  // Arrange
  const { rerender, queryClient } = await watchUntranscribedMeeting();

  // Act
  rerender(detail({ meeting: meeting({ processing_state: "queued" }), tab: "transcript" }));

  // Assert
  expect(queryClient.isFetching()).toBe(0);
});

test("a revision link to a meeting with no transcript reports the error", async () => {
  // Arrange
  refuseTranscript();

  // Act
  renderDetail({ meeting: failed(), tab: "transcript", revisionId: "original" });

  // Assert
  expect(await screen.findByRole("alert")).toHaveTextContent("Not transcribed");
});

test("a transcript failure shows its message", async () => {
  // Arrange
  serveContent();
  server.use(
    http.get("/api/v1/meetings/{meeting_id}/transcript", ({ response }) =>
      response(404).json(errorBody("NOT_FOUND", "No such revision")),
    ),
  );

  // Act
  renderDetail({ tab: "transcript", revisionId: "absent" });

  // Assert
  expect(await screen.findByRole("alert")).toHaveTextContent("No such revision");
});

test("a notes failure shows its message", async () => {
  // Arrange
  serveContent();
  server.use(
    http.get("/api/v1/meetings/{meeting_id}/notes", ({ response }) =>
      response(404).json(errorBody("NOT_FOUND", "Meeting not found")),
    ),
  );

  // Act
  renderDetail();

  // Assert
  expect(await screen.findByRole("alert")).toHaveTextContent("Meeting not found");
});

function failTranscript() {
  serveContent();
  server.use(
    http.get("/api/v1/meetings/{meeting_id}/transcript", ({ response }) =>
      response(422).json(errorBody("VALIDATION_ERROR", "Invalid revision")),
    ),
  );
}

test("a failed transcript request does not promise a transcript", async () => {
  // Arrange
  failTranscript();

  // Act
  renderDetail({ tab: "transcript" });
  await screen.findByRole("alert");

  // Assert
  expect(screen.queryByText("Transcript is not available yet.")).not.toBeInTheDocument();
});

test("a refused revision link does not promise a transcript", async () => {
  // Arrange
  refuseTranscript();

  // Act
  renderDetail({ tab: "transcript", revisionId: "original" });
  await screen.findByRole("alert");

  // Assert
  expect(screen.queryByText("Transcript is not available yet.")).not.toBeInTheDocument();
});

function failNotes() {
  serveContent();
  server.use(
    http.get("/api/v1/meetings/{meeting_id}/notes", ({ response }) =>
      response(422).json(errorBody("VALIDATION_ERROR", "Invalid meeting")),
    ),
  );
}

test("a failed notes request does not promise notes", async () => {
  // Arrange
  failNotes();

  // Act
  renderDetail();
  await screen.findByRole("alert");

  // Assert
  expect(screen.queryByText("No generated notes are available yet.")).not.toBeInTheDocument();
});

test("a meeting sent back to the queue shows its progress despite failed notes", async () => {
  // Arrange
  failNotes();
  const { rerender } = renderDetail();
  await screen.findByRole("alert");

  // Act
  rerender(detail({ meeting: meeting({ processing_state: "queued" }) }));

  // Assert
  expect(screen.getByText(/^Queued$/)).toBeInTheDocument();
});

test("transcript download menu closes when another revision is shown", async () => {
  // Arrange
  serveContent();
  const { rerender } = await openTranscriptDownloads();

  // Act
  rerender(detail({ tab: "transcript", revisionId: "original" }));

  // Assert
  await waitFor(() => expect(screen.queryByRole("menu")).not.toBeInTheDocument());
});

test("transcript download menu stays open when the same revision reloads", async () => {
  // Arrange
  serveContent();
  const { queryClient } = await openTranscriptDownloads();

  // Act
  await queryClient.invalidateQueries();

  // Assert
  expect(screen.getByRole("menu")).toBeInTheDocument();
});
