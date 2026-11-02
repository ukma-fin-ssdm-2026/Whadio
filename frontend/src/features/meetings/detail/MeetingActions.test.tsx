import { fireEvent, screen } from "@testing-library/react";
import { expect, test, vi } from "vitest";
import type { Schemas } from "@/shared/api/types";
import { meetingRead } from "@/shared/testing/fixtures";
import { renderWithProviders } from "@/shared/testing/render";
import { http, server } from "@/shared/testing/server";
import { mapMeeting } from "../model";
import { MeetingActions } from "./MeetingActions";

const FOLDERS: Schemas["FolderRead"][] = [
  { id: "folder", name: "General", is_default: true, meeting_count: 1 },
  { id: "planning", name: "Planning", is_default: false, meeting_count: 0 },
];

function renderActions(
  role: Schemas["Role"] = "member",
  createdByUserId = "member",
  onDeleted = () => {},
) {
  const meeting = mapMeeting(meetingRead({ created_by_user_id: createdByUserId }));
  return renderWithProviders(
    <MeetingActions
      meeting={meeting}
      role={role}
      userId="member"
      folders={FOLDERS}
      onDeleted={onDeleted}
    />,
  );
}

async function openActions(
  role: Schemas["Role"] = "member",
  createdByUserId = "member",
  onDeleted = () => {},
) {
  const rendered = renderActions(role, createdByUserId, onDeleted);
  await rendered.user.click(screen.getByRole("button", { name: "Meeting actions" }));
  return rendered;
}

test("a member can rename a meeting", async () => {
  // Arrange
  const bodies: unknown[] = [];
  server.use(
    http.patch("/api/v1/meetings/{meeting_id}", async ({ request, response }) => {
      bodies.push(await request.json());
      return response(200).json(meetingRead({ name: "Quarterly review" }));
    }),
  );
  const { user } = await openActions();

  // Act
  await user.click(screen.getByRole("menuitem", { name: /Rename/ }));
  fireEvent.change(screen.getByLabelText("Meeting name"), {
    target: { value: "Quarterly review" },
  });
  await user.click(screen.getByRole("button", { name: "Save" }));

  // Assert
  expect(bodies).toEqual([{ name: "Quarterly review" }]);
});

test("a member can move a meeting to a workspace folder", async () => {
  // Arrange
  const bodies: unknown[] = [];
  server.use(
    http.patch("/api/v1/meetings/{meeting_id}", async ({ request, response }) => {
      const body = await request.json();
      bodies.push(body);
      return response(200).json(meetingRead({ folder_id: "planning" }));
    }),
  );
  const { user } = await openActions();

  // Act
  await user.click(screen.getByRole("menuitem", { name: /Move/ }));
  await user.click(screen.getByRole("combobox", { name: "Folder" }));
  await user.click(screen.getByRole("option", { name: "Planning" }));
  await user.click(screen.getByRole("button", { name: "Move" }));

  // Assert
  expect(bodies).toEqual([{ folder_id: "planning" }]);
});

test("a member is not offered deletion of another member's meeting", async () => {
  // Act
  await openActions("member", "another-member");

  // Assert
  expect(screen.queryByRole("menuitem", { name: /Delete/ })).not.toBeInTheDocument();
});

test("a meeting recorder is offered deletion", async () => {
  // Act
  await openActions("member", "member");

  // Assert
  expect(screen.getByRole("menuitem", { name: /Delete/ })).toBeInTheDocument();
});

test("a moderator is offered deletion of another member's meeting", async () => {
  // Act
  await openActions("moderator", "another-member");

  // Assert
  expect(screen.getByRole("menuitem", { name: /Delete/ })).toBeInTheDocument();
});

test("cancelling meeting deletion sends no request", async () => {
  // Arrange
  const remove = vi.fn();
  server.use(
    http.delete("/api/v1/meetings/{meeting_id}", () => {
      remove();
    }),
  );
  const { user } = await openActions();
  await user.click(screen.getByRole("menuitem", { name: /Delete/ }));

  // Act
  await user.click(screen.getByRole("button", { name: "Cancel" }));

  // Assert
  expect(remove).not.toHaveBeenCalled();
});

test("confirming meeting deletion deletes it", async () => {
  // Arrange
  const onDeleted = vi.fn();
  server.use(http.delete("/api/v1/meetings/{meeting_id}", ({ response }) => response(204).empty()));
  const { user } = await openActions("member", "member", onDeleted);
  await user.click(screen.getByRole("menuitem", { name: /Delete/ }));

  // Act
  await user.click(screen.getByRole("button", { name: "Delete meeting" }));

  // Assert
  expect(onDeleted).toHaveBeenCalledOnce();
});
