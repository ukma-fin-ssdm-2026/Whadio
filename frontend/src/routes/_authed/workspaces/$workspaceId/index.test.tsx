import { render, screen, waitFor } from "@testing-library/react";
import { userEvent } from "@testing-library/user-event";
import { afterEach, expect, test, vi } from "vitest";
import { App } from "@/app/App";
import { serveApi } from "@/app/testing";
import { serializeBody } from "@/shared/api/body";
import { meetingRead, page, workspaceRead, workspaceSummary } from "@/shared/testing/fixtures";
import { http, server } from "@/shared/testing/server";

// Observe the multipart FormData before the Node request stream reaches MSW.
vi.mock(import("@/shared/api/body"), { spy: true });

afterEach(() => vi.mocked(serializeBody).mockClear());

const MEMBER_WORKSPACE = workspaceSummary({ my_role: "member" });
const OTHER_WORKSPACE = workspaceSummary({
  id: "another",
  name: "Another workspace",
  my_role: "member",
});

async function openMemberUpload() {
  window.history.replaceState(null, "", "/workspaces/workspace");
  serveApi(true);
  server.use(
    http.get("/api/v1/workspaces", ({ response }) =>
      response(200).json(page([MEMBER_WORKSPACE, OTHER_WORKSPACE])),
    ),
    http.get("/api/v1/workspaces/{workspace_id}", ({ params, response }) =>
      response(200).json(
        workspaceRead(
          params.workspace_id === OTHER_WORKSPACE.id
            ? { ...OTHER_WORKSPACE, default_preset: "summary" }
            : { ...MEMBER_WORKSPACE, default_preset: "detailed" },
        ),
      ),
    ),
    http.get("/api/v1/workspaces/{workspace_id}/folders", ({ response }) =>
      response(200).json(page([])),
    ),
    http.get("/api/v1/workspaces/{workspace_id}/meetings", ({ response }) =>
      response(200).json(page([])),
    ),
  );
  const user = userEvent.setup();
  render(<App />);
  await user.click(await screen.findByRole("button", { name: "Upload" }));
  const select = await screen.findByRole("combobox", { name: "Note preset" });
  return { user, select };
}

test("a member's upload dialog starts at the workspace default", async () => {
  // Act
  const { select } = await openMemberUpload();

  // Assert
  expect(select).toHaveTextContent("Detailed (workspace default)");
});

test.each([
  { scenario: "choosing Interview sends the preset", choice: "Interview", sent: ["interview"] },
  { scenario: "leaving the workspace default omits the preset", choice: null, sent: [] },
])("$scenario", async ({ choice, sent }) => {
  // Arrange
  const { user, select } = await openMemberUpload();
  server.use(
    http.post("/api/v1/workspaces/{workspace_id}/meetings", ({ response }) =>
      response(201).json(meetingRead({ id: "meeting" })),
    ),
  );
  const input = document.querySelector("input[type=file]");
  if (!(input instanceof HTMLInputElement)) throw new Error("The dialog has no file input.");
  await user.upload(input, new File(["RIFF"], "standup.wav", { type: "audio/wav" }));

  // Act
  if (choice !== null) {
    await user.click(select);
    await user.click(screen.getByRole("option", { name: choice }));
  }
  await user.click(screen.getByRole("button", { name: "Queue processing" }));
  await waitFor(() => expect(window.location.pathname).toBe("/meetings/meeting"));

  // Assert
  const form = vi.mocked(serializeBody).mock.results.at(-1)?.value;
  expect(form instanceof FormData ? form.getAll("preset") : form).toEqual(sent);
});

test("reopening a cancelled upload starts at the workspace default again", async () => {
  // Arrange
  const { user, select } = await openMemberUpload();
  await user.click(select);
  await user.click(screen.getByRole("option", { name: "Interview" }));
  await user.click(screen.getByRole("button", { name: "Cancel" }));
  await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument());

  // Act
  await user.click(screen.getByRole("button", { name: "Upload" }));

  // Assert
  expect(await screen.findByRole("combobox", { name: "Note preset" })).toHaveTextContent(
    "Detailed (workspace default)",
  );
});

test("going back to another workspace closes the open upload dialog", async () => {
  // Arrange
  window.history.replaceState(null, "", `/workspaces/${OTHER_WORKSPACE.id}`);
  window.history.pushState(null, "", `/workspaces/${MEMBER_WORKSPACE.id}`);
  const { user, select } = await openMemberUpload();
  await user.click(select);
  await user.click(screen.getByRole("option", { name: "Interview" }));

  // Act
  window.history.back();
  await screen.findByRole("heading", { name: OTHER_WORKSPACE.name, hidden: true });

  // Assert
  await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument());
});
