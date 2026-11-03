import { screen, waitFor, within } from "@testing-library/react";
import { describe, expect, test, vi } from "vitest";
import type { Schemas } from "@/shared/api/types";
import { errorBody, meetingRead } from "@/shared/testing/fixtures";
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

function serveUpdate() {
  const bodies: unknown[] = [];
  server.use(
    http.patch("/api/v1/meetings/{meeting_id}", async ({ request, response }) => {
      bodies.push(await request.json());
      return response(200).json(meetingRead({ name: "Quarterly review" }));
    }),
  );
  return bodies;
}

function refuseUpdate(status: 404 | 422, body: Schemas["ErrorResponse"]) {
  server.use(
    http.patch("/api/v1/meetings/{meeting_id}", ({ response }) => response(status).json(body)),
  );
}

async function rename(name: string) {
  const { user } = await openActions();
  await user.click(screen.getByRole("menuitem", { name: /Rename/ }));
  await user.clear(screen.getByLabelText("Meeting name"));
  if (name) await user.type(screen.getByLabelText("Meeting name"), name);
  await user.click(screen.getByRole("button", { name: "Save" }));
  return user;
}

async function moveToPlanning() {
  const { user } = await openActions();
  await user.click(screen.getByRole("menuitem", { name: /Move/ }));
  await user.click(screen.getByRole("combobox", { name: "Folder" }));
  await user.click(screen.getByRole("option", { name: "Planning" }));
  await user.click(screen.getByRole("button", { name: "Move" }));
  return user;
}

test("a member can rename a meeting", async () => {
  // Arrange
  const bodies = serveUpdate();

  // Act
  await rename("Quarterly review");

  // Assert
  await waitFor(() => expect(bodies).toEqual([{ name: "Quarterly review" }]));
});

describe.each([
  ["an empty name", "", "Enter a meeting name"],
  ["a blank name", "   ", "Enter a meeting name"],
  ["a name over 200 characters", "m".repeat(201), "Use 200 characters or fewer"],
])("%s", (_, name, message) => {
  test("is refused on the field", async () => {
    // Act
    await rename(name);

    // Assert
    expect(screen.getByLabelText("Meeting name")).toHaveAccessibleDescription(message);
  });

  test("is not sent", async () => {
    // Arrange
    const bodies = serveUpdate();

    // Act
    await rename(name);

    // Assert
    expect(bodies).toEqual([]);
  });
});

test("a rejected name shows the server's reason on the field", async () => {
  // Arrange
  refuseUpdate(422, {
    error: {
      code: "VALIDATION_ERROR",
      message: "Request contains invalid fields",
      details: [{ field: "name", message: "Name contains no visible character" }],
      request_id: "request",
    },
  });

  // Act
  await rename("Quarterly review");

  // Assert
  await waitFor(() =>
    expect(screen.getByLabelText("Meeting name")).toHaveAccessibleDescription(
      "Name contains no visible character",
    ),
  );
});

test("a refused rename leaves no error in the move dialog", async () => {
  // Arrange
  refuseUpdate(422, errorBody("VALIDATION_ERROR", "Request contains invalid fields"));
  const user = await rename("Quarterly review");
  await screen.findByText("Request contains invalid fields");
  await user.click(screen.getByRole("button", { name: "Cancel" }));
  await user.click(screen.getByRole("button", { name: "Meeting actions" }));

  // Act
  await user.click(screen.getByRole("menuitem", { name: /Move/ }));

  // Assert
  expect(screen.queryByText("Request contains invalid fields")).not.toBeInTheDocument();
});

test("a member can move a meeting to a workspace folder", async () => {
  // Arrange
  const bodies = serveUpdate();

  // Act
  await moveToPlanning();

  // Assert
  await waitFor(() => expect(bodies).toEqual([{ folder_id: "planning" }]));
});

test("a failed move shows the server's message", async () => {
  // Arrange
  refuseUpdate(404, errorBody("NOT_FOUND", "The folder no longer exists"));

  // Act
  await moveToPlanning();

  // Assert
  expect(await screen.findByText("The folder no longer exists")).toBeVisible();
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

test.for(["moderator", "owner"] as const)(
  "a %s is offered deletion of another member's meeting",
  async (role) => {
    // Act
    await openActions(role, "another-member");

    // Assert
    expect(screen.getByRole("menuitem", { name: /Delete/ })).toBeInTheDocument();
  },
);

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
  await waitFor(() => expect(onDeleted).toHaveBeenCalledOnce());
});

test("a failed deletion shows the server's message", async () => {
  // Arrange
  server.use(
    http.delete("/api/v1/meetings/{meeting_id}", ({ response }) =>
      response(403).json(errorBody("INSUFFICIENT_ROLE", "You cannot delete this meeting")),
    ),
  );
  const { user } = await openActions();
  await user.click(screen.getByRole("menuitem", { name: /Delete/ }));

  // Act
  await user.click(screen.getByRole("button", { name: "Delete meeting" }));

  // Assert
  expect(await screen.findByRole("alert")).toHaveTextContent("You cannot delete this meeting");
});

test("renaming offers only the name, not the date or time", async () => {
  // Arrange
  const { user } = await openActions();

  // Act
  await user.click(screen.getByRole("menuitem", { name: /Rename/ }));

  // Assert
  expect(
    within(screen.getByRole("dialog"))
      .getAllByRole("textbox")
      .map((field) => field.getAttribute("name")),
  ).toEqual(["name"]);
});
