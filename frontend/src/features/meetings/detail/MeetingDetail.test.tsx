import { screen, waitFor } from "@testing-library/react";
import type { ComponentProps } from "react";
import { expect, test } from "vitest";
import { ExportMenu } from "@/features/export/components/ExportMenu";
import type { Schemas } from "@/shared/api/types";
import { errorBody, meetingRead, noteRead, page, transcriptRead } from "@/shared/testing/fixtures";
import { createTestQueryClient, renderWithProviders } from "@/shared/testing/render";
import { http, server } from "@/shared/testing/server";
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

test("a failed meeting shows its reason on the notes tab", () => {
  // Act
  renderDetail({
    meeting: meeting({ processing_state: "failed", failure_reason: "No audio track" }),
  });

  // Assert
  expect(screen.getByRole("alert")).toHaveTextContent("No audio track");
});

test("a failed meeting without a reason says processing failed", () => {
  // Act
  renderDetail({ meeting: meeting({ processing_state: "failed" }) });

  // Assert
  expect(screen.getByRole("alert")).toHaveTextContent("Processing failed");
});

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

test("a meeting with no transcript yet raises no alert", async () => {
  // Arrange
  const requests = serveContent();
  server.use(
    http.get("/api/v1/meetings/{meeting_id}/transcript", ({ response }) => {
      requests.push("refused");
      return response(409).json(errorBody("NOT_TRANSCRIBED", "Not transcribed yet"));
    }),
  );

  // Act
  renderDetail({ tab: "transcript" });
  await screen.findByText("Transcript is not available yet.");

  // Assert
  expect(screen.queryByRole("alert")).not.toBeInTheDocument();
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
