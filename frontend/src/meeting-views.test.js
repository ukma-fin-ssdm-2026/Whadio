import assert from "node:assert/strict";
import { after, before, test } from "node:test";
import { openAppEnvironment } from "./app-test-environment.js";

let environment;
let MeetingLibrary;
let MeetingDetail;
let act;
let createElement;
let createRoot;

before(async () => {
  environment = await openAppEnvironment("https://app.example/");
  ({ act, createElement, createRoot } = environment);
  ({ MeetingLibrary, MeetingDetail } = environment.app);
});

after(async () => {
  await environment?.close();
});

function meeting(changes = {}) {
  return {
    id: "meeting",
    workspaceId: "workspace",
    title: "Weekly sync",
    date: "2026-10-25T10:00:00Z",
    state: "processed",
    duration: "5s",
    source: "Google Meet",
    recordingAvailable: false,
    failureReason: null,
    ...changes,
  };
}

function transcript(revisionId) {
  return {
    revision: { id: revisionId, revision_type: revisionId === "original" ? "original" : "edited" },
    original_revision_id: "original",
    is_edited: true,
    speakers: [],
    segments: [],
  };
}

async function render(component, props) {
  const container = document.createElement("div");
  document.body.append(container);
  const root = createRoot(container);
  const rerender = async (changes = {}) => {
    await act(async () => {
      root.render(createElement(component, { ...props, ...changes }));
    });
  };
  await rerender();
  return { container, rerender };
}

function renderLibrary(item) {
  return render(MeetingLibrary, {
    title: "Workspace library",
    meetings: [item],
    query: "",
    stateFilter: "all",
    onQuery: () => {},
    onStateFilter: () => {},
    onMeeting: () => {},
    selectedMeetingId: "",
  });
}

function renderDetail(changes = {}) {
  return render(MeetingDetail, {
    meeting: meeting(),
    tab: "notes",
    transcriptQuery: "",
    onTab: () => {},
    onTranscriptQuery: () => {},
    notes: { content: "Saved notes" },
    transcript: null,
    onRevision: () => {},
    recordingUrl: "",
    loading: false,
    ...changes,
  });
}

const interactive = 'button, a[href], input, select, [role="button"], [tabindex="0"]';

for (const [state, label] of [
  ["recording", "Recording"],
  ["queued", "Queued"],
  ["processing", "Processing"],
]) {
  test(`${state} library row is labelled ${label}`, async () => {
    // Arrange
    const { container } = await renderLibrary(meeting({ state }));

    // Act
    const status = container.querySelector(".processing-status");

    // Assert
    assert.equal(status?.textContent, label);
  });
}

test("in-progress library row offers no control besides opening the meeting", async () => {
  // Arrange
  const { container } = await renderLibrary(meeting({ state: "queued" }));

  // Act
  const controls = container.querySelectorAll(`.meeting-row :is(${interactive})`);

  // Assert
  assert.equal(controls.length, 1);
});

test("in-progress library row shows a progress indicator", async () => {
  // Arrange
  const { container } = await renderLibrary(meeting({ state: "queued" }));

  // Act
  const progress = container.querySelector('[role="progressbar"]');

  // Assert
  assert.ok(progress);
});

test("processed library row shows no progress indicator", async () => {
  // Arrange
  const { container } = await renderLibrary(meeting());

  // Act
  const progress = container.querySelector('[role="progressbar"]');

  // Assert
  assert.equal(progress, null);
});

test("meeting header has no workspace access control", async () => {
  // Arrange
  const { container } = await renderDetail();

  // Act
  const access = container.querySelector('[aria-label="Workspace access"]');

  // Assert
  assert.equal(access, null);
});

test("meeting header names the source as text beside the date", async () => {
  // Arrange
  const { container } = await renderDetail();

  // Act
  const meta = container.querySelector(".meeting-date").textContent;

  // Assert
  assert.match(meta, / · Google Meet$/);
});

test("queued meeting notes panel is headed Queued", async () => {
  // Arrange
  const { container } = await renderDetail({ meeting: meeting({ state: "queued" }), notes: null });

  // Act
  const heading = container.querySelector(".processing-panel p").textContent;

  // Assert
  assert.equal(heading, "Queued");
});

test("in-progress notes panel offers no control", async () => {
  // Arrange
  const { container } = await renderDetail({ meeting: meeting({ state: "queued" }), notes: null });

  // Act
  const controls = container.querySelectorAll(`.processing-panel :is(${interactive})`);

  // Assert
  assert.equal(controls.length, 0);
});

test("transcript download menu closes when another revision is shown", async () => {
  // Arrange
  const { container, rerender } = await renderDetail({
    tab: "transcript",
    transcript: transcript("edited"),
  });
  await act(async () => {
    container.querySelector('[aria-label="Download transcript"]').click();
  });

  // Act
  await rerender({ tab: "transcript", transcript: transcript("original") });

  // Assert
  assert.equal(
    container.querySelector('[aria-label="Download transcript"]').getAttribute("aria-expanded"),
    "false",
  );
});

test("transcript download menu stays open when the same revision reloads", async () => {
  // Arrange
  const { container, rerender } = await renderDetail({
    tab: "transcript",
    transcript: transcript("edited"),
  });
  await act(async () => {
    container.querySelector('[aria-label="Download transcript"]').click();
  });

  // Act
  await rerender({ tab: "transcript", transcript: transcript("edited") });

  // Assert
  assert.equal(
    container.querySelector('[aria-label="Download transcript"]').getAttribute("aria-expanded"),
    "true",
  );
});
