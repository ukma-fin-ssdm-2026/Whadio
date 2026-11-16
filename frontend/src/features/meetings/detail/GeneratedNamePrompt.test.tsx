import { screen, waitFor } from "@testing-library/react";
import { expect, test } from "vitest";
import type { Schemas } from "@/shared/api/types";
import { errorBody, meetingRead } from "@/shared/testing/fixtures";
import { renderWithProviders } from "@/shared/testing/render";
import { http, server } from "@/shared/testing/server";
import { mapMeeting } from "../model";
import { GeneratedNamePrompt } from "./GeneratedNamePrompt";

const PROMPT = { name: "Suggested meeting name" };

function renderPrompt(changes: Partial<Schemas["MeetingRead"]> = {}) {
  const meeting = mapMeeting(meetingRead({ name_is_generated: true, ...changes }));
  return renderWithProviders(<GeneratedNamePrompt meeting={meeting} />);
}

function serveNaming() {
  const names: unknown[] = [];
  server.use(
    http.patch("/api/v1/meetings/{meeting_id}", async ({ request, response }) => {
      const { name } = await request.json();
      names.push(name);
      return response(200).json(meetingRead());
    }),
  );
  return names;
}

async function openRename() {
  const { user } = renderPrompt();
  await user.click(screen.getByRole("button", { name: "Rename" }));
  return user;
}

test("a processed meeting with a generated name asks to keep or rename it", () => {
  // Act
  renderPrompt();

  // Assert
  expect(screen.getByRole("group", PROMPT)).toBeInTheDocument();
});

test.for([
  ["a name a member gave", { name_is_generated: false }],
  ["a failed meeting", { processing_state: "failed" }],
  ["a meeting still being processed", { processing_state: "processing" }],
] as const)("%s is not asked about", ([, changes]) => {
  // Act
  renderPrompt(changes);

  // Assert
  expect(screen.queryByRole("group", PROMPT)).not.toBeInTheDocument();
});

test("keeping the name saves it unchanged", async () => {
  // Arrange
  const names = serveNaming();
  const { user } = renderPrompt();

  // Act
  await user.click(screen.getByRole("button", { name: "Keep name" }));

  // Assert
  await waitFor(() => expect(names).toEqual(["Weekly sync"]));
});

test("keeping the name is confirmed", async () => {
  // Arrange
  serveNaming();
  const { user } = renderPrompt();

  // Act
  await user.click(screen.getByRole("button", { name: "Keep name" }));

  // Assert
  expect(await screen.findByText("Name kept.")).toBeInTheDocument();
});

test("a name the server refuses to keep says why", async () => {
  // Arrange
  server.use(
    http.patch("/api/v1/meetings/{meeting_id}", ({ response }) =>
      response(404).json(errorBody("NOT_FOUND", "Meeting not found")),
    ),
  );
  const { user } = renderPrompt();

  // Act
  await user.click(screen.getByRole("button", { name: "Keep name" }));

  // Assert
  expect(await screen.findByText("Meeting not found")).toBeInTheDocument();
});

test("renaming starts from the generated name", async () => {
  // Act
  await openRename();

  // Assert
  expect(screen.getByLabelText("Meeting name")).toHaveValue("Weekly sync");
});

test("renaming saves the new name", async () => {
  // Arrange
  const names = serveNaming();
  const user = await openRename();

  // Act
  await user.clear(screen.getByLabelText("Meeting name"));
  await user.type(screen.getByLabelText("Meeting name"), "Quarterly review");
  await user.click(screen.getByRole("button", { name: "Save" }));

  // Assert
  await waitFor(() => expect(names).toEqual(["Quarterly review"]));
});

test("a blank name is refused before it is sent", async () => {
  // Arrange
  const names = serveNaming();
  const user = await openRename();

  // Act
  await user.clear(screen.getByLabelText("Meeting name"));
  await user.type(screen.getByLabelText("Meeting name"), "   ");
  await user.click(screen.getByRole("button", { name: "Save" }));

  // Assert
  expect([screen.getByLabelText("Meeting name").getAttribute("aria-invalid"), names]).toEqual([
    "true",
    [],
  ]);
});

test("dismissing the prompt hides it", async () => {
  // Arrange
  const { user } = renderPrompt();

  // Act
  await user.click(screen.getByRole("button", { name: "Not now" }));

  // Assert
  expect(screen.queryByRole("group", PROMPT)).not.toBeInTheDocument();
});

test("a dismissed prompt asks again when the meeting is opened again", async () => {
  // Arrange
  const { user, unmount } = renderPrompt();
  await user.click(screen.getByRole("button", { name: "Not now" }));
  unmount();

  // Act
  renderPrompt();

  // Assert
  expect(screen.getByRole("group", PROMPT)).toBeInTheDocument();
});
