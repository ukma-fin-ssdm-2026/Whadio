import { render, screen, waitFor, within } from "@testing-library/react";
import { type UserEvent, userEvent } from "@testing-library/user-event";
import { HttpResponse, http } from "msw";
import { expect, test } from "vitest";
import { App } from "@/app/App";
import { serveApi } from "@/app/testing";
import { transcriptRead } from "@/shared/testing/fixtures";
import { server } from "@/shared/testing/server";

const SPOKEN = transcriptRead({
  segments: [
    {
      id: "one",
      speaker_id: null,
      start_seconds: 0,
      end_seconds: 5,
      text: "We ship what audio on Friday",
    },
  ],
});

const SAVED = transcriptRead({
  ...SPOKEN,
  revision: { ...SPOKEN.revision, id: "edited", revision_type: "edited" },
  is_edited: true,
});

const leaveDialog = () => screen.queryByRole("dialog", { name: "Discard unsaved changes?" });
const currentPath = () => window.location.pathname + window.location.search;

async function startEditing(path = "/meetings/meeting?tab=transcript") {
  window.history.replaceState(null, "", path);
  serveApi(true);
  server.use(
    http.get("/api/v1/meetings/meeting/transcript", () => HttpResponse.json(SPOKEN)),
    http.post("/api/v1/meetings/meeting/transcript/revisions", () =>
      HttpResponse.json(SAVED, { status: 201 }),
    ),
  );
  render(<App />);
  const user = userEvent.setup();
  await user.click(await screen.findByRole("button", { name: "Edit transcript" }));
  return user;
}

async function correct(user: UserEvent) {
  await user.click(screen.getByRole("button", { name: /^Edit text at 00:00/ }));
  await user.type(screen.getByLabelText("Text at 00:00"), " in full");
  await user.tab();
}

async function saveCorrection(path?: string) {
  const user = await startEditing(path);
  await correct(user);
  await user.click(screen.getByRole("button", { name: "Save" }));
  return user;
}

test("the notes tab asks before unsaved changes are lost", async () => {
  // Arrange
  const user = await startEditing();
  await correct(user);

  // Act
  await user.click(screen.getByRole("tab", { name: "Notes" }));

  // Assert
  expect(await screen.findByRole("dialog")).toHaveAccessibleName("Discard unsaved changes?");
});

test("leaving the meeting asks before unsaved changes are lost", async () => {
  // Arrange
  const user = await startEditing();
  await correct(user);
  const breadcrumb = screen.getByRole("navigation", { name: "Breadcrumb" });

  // Act
  await user.click(within(breadcrumb).getByRole("link", { name: "Home" }));

  // Assert
  expect(await screen.findByRole("dialog")).toHaveAccessibleName("Discard unsaved changes?");
});

test("keeping the changes stays in the editor", async () => {
  // Arrange
  const user = await startEditing();
  await correct(user);
  await user.click(screen.getByRole("tab", { name: "Notes" }));

  // Act
  await user.click(
    within(await screen.findByRole("dialog")).getByRole("button", { name: "Cancel" }),
  );

  // Assert
  expect(screen.getByText("Changed")).toBeInTheDocument();
});

test("discarding the changes opens the notes", async () => {
  // Arrange
  const user = await startEditing();
  await correct(user);
  await user.click(screen.getByRole("tab", { name: "Notes" }));
  const dialog = await screen.findByRole("dialog");

  // Act
  await user.click(within(dialog).getByRole("button", { name: "Discard changes" }));

  // Assert
  await waitFor(() => expect(currentPath()).toBe("/meetings/meeting"));
});

test("the recording tab keeps the editor without asking", async () => {
  // Arrange
  const user = await startEditing();
  await correct(user);

  // Act
  await user.click(screen.getByRole("tab", { name: "Recording" }));
  await waitFor(() => expect(currentPath()).toBe("/meetings/meeting?tab=recording"));

  // Assert
  expect(leaveDialog()).not.toBeInTheDocument();
});

test("an editor without changes is left without asking", async () => {
  // Arrange
  const user = await startEditing();

  // Act
  await user.click(screen.getByRole("tab", { name: "Notes" }));
  await waitFor(() => expect(currentPath()).toBe("/meetings/meeting"));

  // Assert
  expect(leaveDialog()).not.toBeInTheDocument();
});

test("a saved correction is left without asking", async () => {
  // Arrange
  const user = await saveCorrection();
  await screen.findByRole("button", { name: "View original transcript" });

  // Act
  await user.click(screen.getByRole("tab", { name: "Notes" }));
  await waitFor(() => expect(currentPath()).toBe("/meetings/meeting"));

  // Assert
  expect(leaveDialog()).not.toBeInTheDocument();
});

test("a correction saved from a revision link opens the current transcript without asking", async () => {
  // Act
  await saveCorrection("/meetings/meeting?revision_id=revision");

  // Assert
  await waitFor(() => expect(currentPath()).toBe("/meetings/meeting?tab=transcript"));
});

test("closing the page with unsaved changes asks first", async () => {
  // Arrange
  const user = await startEditing();
  await correct(user);
  const closing = new Event("beforeunload", { cancelable: true });

  // Act
  window.dispatchEvent(closing);

  // Assert
  expect(closing.defaultPrevented).toBe(true);
});

test("closing the page without changes asks nothing", async () => {
  // Arrange
  await startEditing();
  const closing = new Event("beforeunload", { cancelable: true });

  // Act
  window.dispatchEvent(closing);

  // Assert
  expect(closing.defaultPrevented).toBe(false);
});
