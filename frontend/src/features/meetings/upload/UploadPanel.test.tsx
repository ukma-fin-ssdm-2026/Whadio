import { screen, waitFor } from "@testing-library/react";
import { expect, test, vi } from "vitest";
import { errorBody, meetingRead } from "@/shared/testing/fixtures";
import { renderWithProviders } from "@/shared/testing/render";
import { http, server } from "@/shared/testing/server";
import { UploadPanel } from "./UploadPanel";

const RECORDING = new File(["RIFF"], "standup.wav", { type: "audio/wav" });

async function openDialog(onUploaded: (id: string) => void = () => {}) {
  const view = renderWithProviders(
    <UploadPanel
      workspaceId="workspace"
      presetField={<p>Preset slot</p>}
      onUploaded={onUploaded}
    />,
  );
  await view.user.click(screen.getByRole("button", { name: "Upload" }));
  return view;
}

async function submitRecording(onUploaded?: (id: string) => void) {
  const { user, container } = await openDialog(onUploaded);
  const input = document.querySelector("input[type=file]");
  if (!(input instanceof HTMLInputElement)) throw new Error("The dialog has no file input.");
  await user.upload(input, RECORDING);
  await user.click(screen.getByRole("button", { name: "Queue processing" }));
  return { user, container };
}

function serveCreated() {
  server.use(
    http.post("/api/v1/workspaces/{workspace_id}/meetings", ({ response }) =>
      response(201).json(meetingRead({ id: "created" })),
    ),
  );
}

test("the dialog shows the preset the app supplies", async () => {
  // Act
  await openDialog();

  // Assert
  expect(screen.getByText("Preset slot")).toBeInTheDocument();
});

test("submitting without a file asks for one", async () => {
  // Arrange
  const { user } = await openDialog();

  // Act
  await user.click(screen.getByRole("button", { name: "Queue processing" }));

  // Assert
  expect(screen.getByRole("alert")).toHaveTextContent("Select an audio or video file.");
});

test("a finished upload opens the new meeting", async () => {
  // Arrange
  serveCreated();
  const onUploaded = vi.fn();

  // Act
  await submitRecording(onUploaded);

  // Assert
  await waitFor(() => expect(onUploaded).toHaveBeenCalledExactlyOnceWith("created"));
});

test("a finished upload closes the dialog", async () => {
  // Arrange
  serveCreated();

  // Act
  await submitRecording();

  // Assert
  await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument());
});

test("a refused upload shows the server's message", async () => {
  // Arrange
  server.use(
    http.post("/api/v1/workspaces/{workspace_id}/meetings", ({ response }) =>
      response(415).json(errorBody("UNSUPPORTED_MEDIA_TYPE", "Not a recording")),
    ),
  );

  // Act
  await submitRecording();

  // Assert
  expect(await screen.findByRole("alert")).toHaveTextContent("Not a recording");
});

test("a refused upload keeps the dialog open", async () => {
  // Arrange
  server.use(
    http.post("/api/v1/workspaces/{workspace_id}/meetings", ({ response }) =>
      response(415).json(errorBody("UNSUPPORTED_MEDIA_TYPE", "Not a recording")),
    ),
  );
  await submitRecording();

  // Act
  await screen.findByRole("alert");

  // Assert
  expect(screen.getByRole("dialog")).toBeInTheDocument();
});
