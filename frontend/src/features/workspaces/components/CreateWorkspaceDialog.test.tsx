import { screen, waitFor } from "@testing-library/react";
import { expect, test, vi } from "vitest";
import { workspaceRead } from "@/shared/testing/fixtures";
import { renderWithProviders } from "@/shared/testing/render";
import { http, server } from "@/shared/testing/server";
import { CreateWorkspaceDialog } from "./CreateWorkspaceDialog";

const CREATED = workspaceRead({ id: "team", name: "Research Team", member_count: 1 });

function serveCreate() {
  const requests: unknown[] = [];
  server.use(
    http.post("/api/v1/workspaces", async ({ request, response }) => {
      requests.push(await request.json());
      return response(201).json(CREATED);
    }),
  );
  return requests;
}

async function openDialog() {
  const onCreated = vi.fn();
  const rendered = renderWithProviders(<CreateWorkspaceDialog onCreated={onCreated} />);
  await rendered.user.click(screen.getByRole("button", { name: "Create workspace" }));
  return { ...rendered, onCreated };
}

test("creates a workspace with its chosen notes preset", async () => {
  // Arrange
  const requests = serveCreate();
  const { user, onCreated } = await openDialog();
  await user.type(screen.getByLabelText(/^Workspace name/), "Research Team");
  await user.click(screen.getByRole("combobox", { name: "Default notes preset" }));
  await user.click(screen.getByRole("option", { name: "Detailed" }));

  // Act
  await user.click(screen.getByRole("button", { name: /^Create$/ }));

  // Assert
  await waitFor(() => expect(onCreated).toHaveBeenCalledExactlyOnceWith("team"));
  expect(requests).toEqual([{ name: "Research Team", default_preset: "detailed" }]);
});

test("an empty workspace name is refused without sending", async () => {
  // Arrange
  const requests = serveCreate();
  const { user } = await openDialog();

  // Act
  await user.click(screen.getByRole("button", { name: /^Create$/ }));

  // Assert
  expect(screen.getByLabelText(/^Workspace name/)).toHaveAccessibleDescription(
    "Enter a workspace name",
  );
  expect(requests).toEqual([]);
});

test("a name over 100 characters is refused without sending", async () => {
  // Arrange
  const requests = serveCreate();
  const { user } = await openDialog();
  await user.type(screen.getByLabelText(/^Workspace name/), "w".repeat(101));

  // Act
  await user.click(screen.getByRole("button", { name: /^Create$/ }));

  // Assert
  expect(screen.getByLabelText(/^Workspace name/)).toHaveAccessibleDescription(
    "Use 100 characters or fewer",
  );
  expect(requests).toEqual([]);
});

test("a server validation error is shown on the workspace name", async () => {
  // Arrange
  server.use(
    http.post("/api/v1/workspaces", ({ response }) =>
      response(422).json({
        error: {
          code: "VALIDATION_ERROR",
          message: "Request contains invalid fields",
          details: [{ field: "name", message: "Name contains no visible character" }],
          request_id: "request",
        },
      }),
    ),
  );
  const { user } = await openDialog();
  await user.type(screen.getByLabelText(/^Workspace name/), "Research Team");

  // Act
  await user.click(screen.getByRole("button", { name: /^Create$/ }));

  // Assert
  await waitFor(() =>
    expect(screen.getByLabelText(/^Workspace name/)).toHaveAccessibleDescription(
      "Name contains no visible character",
    ),
  );
});
