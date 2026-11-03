import { screen, waitFor, waitForElementToBeRemoved } from "@testing-library/react";
import { describe, expect, test, vi } from "vitest";
import type { Schemas } from "@/shared/api/types";
import { workspaceRead } from "@/shared/testing/fixtures";
import { renderWithProviders } from "@/shared/testing/render";
import { http, server } from "@/shared/testing/server";
import { CreateWorkspaceDialog } from "./CreateWorkspaceDialog";

const CREATED = workspaceRead({ id: "team", name: "Research Team", member_count: 1 });

type ErrorEnvelope = Schemas["ErrorResponse"];

const errorEnvelope = (
  code: ErrorEnvelope["error"]["code"],
  message: string,
  details: ErrorEnvelope["error"]["details"] = [],
): ErrorEnvelope => ({ error: { code, message, details, request_id: "request" } });

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

function refuseCreate(status: 400 | 422, body: ErrorEnvelope) {
  server.use(http.post("/api/v1/workspaces", ({ response }) => response(status).json(body)));
}

async function openDialog() {
  const onCreated = vi.fn();
  const rendered = renderWithProviders(<CreateWorkspaceDialog onCreated={onCreated} />);
  await rendered.user.click(screen.getByRole("button", { name: "Create workspace" }));
  return { ...rendered, onCreated };
}

async function submit(name: string) {
  const opened = await openDialog();
  if (name) await opened.user.type(screen.getByLabelText(/^Workspace name/), name);
  await opened.user.click(screen.getByRole("button", { name: /^Create$/ }));
  return opened;
}

test("sends the name and the chosen preset", async () => {
  // Arrange
  const requests = serveCreate();
  const { user } = await openDialog();
  await user.type(screen.getByLabelText(/^Workspace name/), "Research Team");
  await user.click(screen.getByRole("combobox", { name: "Default notes preset" }));
  await user.click(screen.getByRole("option", { name: "Detailed" }));

  // Act
  await user.click(screen.getByRole("button", { name: /^Create$/ }));

  // Assert
  await waitFor(() =>
    expect(requests).toEqual([{ name: "Research Team", default_preset: "detailed" }]),
  );
});

test("hands over the created workspace's id", async () => {
  // Arrange
  serveCreate();

  // Act
  const { onCreated } = await submit("Research Team");

  // Assert
  await waitFor(() => expect(onCreated).toHaveBeenCalledExactlyOnceWith("team"));
});

describe.each([
  ["an empty", ""],
  ["a blank", "   "],
])("%s workspace name", (_, name) => {
  test("asks for a workspace name", async () => {
    // Act
    await submit(name);

    // Assert
    expect(screen.getByLabelText(/^Workspace name/)).toHaveAccessibleDescription(
      "Enter a workspace name",
    );
  });

  test("is not sent", async () => {
    // Arrange
    const requests = serveCreate();

    // Act
    await submit(name);

    // Assert
    expect(requests).toEqual([]);
  });
});

describe("a name over 100 characters", () => {
  test("asks for a shorter name", async () => {
    // Act
    await submit("w".repeat(101));

    // Assert
    expect(screen.getByLabelText(/^Workspace name/)).toHaveAccessibleDescription(
      "Use 100 characters or fewer",
    );
  });

  test("is not sent", async () => {
    // Arrange
    const requests = serveCreate();

    // Act
    await submit("w".repeat(101));

    // Assert
    expect(requests).toEqual([]);
  });
});

test("a rejected name shows the server's reason on the name", async () => {
  // Arrange
  refuseCreate(
    422,
    errorEnvelope("VALIDATION_ERROR", "Request contains invalid fields", [
      { field: "name", message: "Name contains no visible character" },
    ]),
  );

  // Act
  await submit("Research Team");

  // Assert
  await waitFor(() =>
    expect(screen.getByLabelText(/^Workspace name/)).toHaveAccessibleDescription(
      "Name contains no visible character",
    ),
  );
});

test("a rejected preset shows the server's reason on the preset", async () => {
  // Arrange
  refuseCreate(
    422,
    errorEnvelope("VALIDATION_ERROR", "Request contains invalid fields", [
      { field: "default_preset", message: "Unknown preset" },
    ]),
  );

  // Act
  await submit("Research Team");

  // Assert
  await waitFor(() =>
    expect(
      screen.getByRole("combobox", { name: "Default notes preset" }),
    ).toHaveAccessibleDescription("Unknown preset"),
  );
});

test("a refusal without field details shows the server's message under the form", async () => {
  // Arrange
  refuseCreate(400, errorEnvelope("MALFORMED_REQUEST", "The request body is not valid JSON"));

  // Act
  await submit("Research Team");

  // Assert
  expect(await screen.findByRole("alert")).toHaveTextContent("The request body is not valid JSON");
});

test("reopening after a create shows an empty name", async () => {
  // Arrange
  serveCreate();
  const { user } = await submit("Research Team");
  await waitForElementToBeRemoved(() => screen.queryByRole("dialog"));

  // Act
  await user.click(screen.getByRole("button", { name: "Create workspace" }));

  // Assert
  expect(screen.getByLabelText(/^Workspace name/)).toHaveValue("");
});

test("escape keeps the form while the workspace is being created", async () => {
  // Arrange
  server.use(http.post("/api/v1/workspaces", () => new Promise<Response>(() => {})));
  const { user } = await submit("Research Team");
  await screen.findByRole("button", { name: "Creating..." });
  await user.click(screen.getByLabelText(/^Workspace name/));

  // Act
  await user.keyboard("{Escape}");

  // Assert
  expect(screen.getByLabelText(/^Workspace name/)).toHaveValue("Research Team");
});
