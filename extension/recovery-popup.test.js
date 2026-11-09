// @vitest-environment jsdom
import popupHtml from "./popup.html?raw";
import { showRecovery } from "./recovery-popup.js";

const recording = { id: "one", startedAt: 1 };

test("a signed-out popup shows a sign-in hint and no recovery controls", async () => {
  // Arrange
  chrome.runtime.sendMessage.mockResolvedValue({ recordings: [], locked: true });

  // Act
  await showRecovery();

  // Assert
  expect({
    buttons: document.querySelectorAll("#recovery button").length,
    hint: document.getElementById("recovery-error").textContent,
  }).toEqual({
    buttons: 0,
    hint: "Sign in to the original account and server to recover your saved recordings.",
  });
});

test("an old account's delayed response cannot repopulate recovery controls after signing out", async () => {
  // Arrange
  let finishOldRequest;
  chrome.runtime.sendMessage.mockImplementationOnce(
    () =>
      new Promise((resolve) => {
        finishOldRequest = resolve;
      }),
  );
  const initial = showRecovery();
  chrome.runtime.sendMessage.mockResolvedValue({ recordings: [], locked: true });

  // Act
  chrome.storage.onChanged.addListener.mock.calls[0][0]({}, "session");
  await Promise.resolve();
  finishOldRequest({ recordings: [recording] });
  await initial;

  // Assert
  expect(document.querySelectorAll("#recovery button")).toHaveLength(0);
});

test.for([
  { label: "Retry download", reply: { recordings: [recording] } },
  { label: "Discard", reply: { recordings: [recording] } },
  { label: "Retry download", reply: { error: "old account failure" } },
  { label: "Discard", reply: { error: "old account failure" } },
])("ignores a delayed $label reply after sign-out", async ({ label, reply }) => {
  // Arrange
  await showRecovery();
  vi.spyOn(window, "confirm").mockReturnValue(true);
  const { promise, resolve } = Promise.withResolvers();
  chrome.runtime.sendMessage
    .mockReturnValueOnce(promise)
    .mockResolvedValue({ recordings: [], locked: true });

  // Act
  await click(label);
  chrome.storage.onChanged.addListener.mock.calls[0][0]({}, "session");
  await vi.waitFor(() => expect(document.getElementById("recovery-error").hidden).toBe(false));
  resolve(reply);
  await new Promise((done) => setTimeout(done, 0));

  // Assert
  expect({
    controls: document.querySelectorAll("#recovery button").length,
    message: document.getElementById("recovery-error").textContent,
  }).toEqual({
    controls: 0,
    message: "Sign in to the original account and server to recover your saved recordings.",
  });
});

beforeEach(() => {
  document.body.innerHTML = popupHtml;
  globalThis.chrome = {
    runtime: { sendMessage: vi.fn(async () => ({ recordings: [recording] })) },
    storage: { onChanged: { addListener: vi.fn() } },
  };
});

afterEach(() => {
  vi.useRealTimers();
  vi.restoreAllMocks();
});

async function click(label) {
  [...document.querySelectorAll("#recovery button")]
    .find((button) => button.textContent === label)
    .click();
  await vi.waitFor(() => {
    expect(chrome.runtime.sendMessage).toHaveBeenCalledTimes(2);
  });
}

test("shows the signed-in account's local recovery without needing a Meet tab", async () => {
  // Arrange
  const section = document.getElementById("recovery");

  // Act
  await showRecovery();

  // Assert
  expect({
    hidden: section.hidden,
    actions: [...section.querySelectorAll("button")].map((button) => button.textContent),
  }).toEqual({ hidden: false, actions: ["Retry download", "Discard"] });
});

test("retry downloads the chosen recording and removes its recovery controls on success", async () => {
  // Arrange
  await showRecovery();
  chrome.runtime.sendMessage.mockResolvedValue({ recordings: [] });

  // Act
  await click("Retry download");

  // Assert
  expect({
    request: chrome.runtime.sendMessage.mock.calls[1][0],
    hidden: document.getElementById("recovery").hidden,
  }).toEqual({ request: { type: "recovery-retry", id: "one" }, hidden: true });
});

test("a failed retry shows a readable error and leaves both recovery actions usable", async () => {
  // Arrange
  await showRecovery();
  chrome.runtime.sendMessage.mockResolvedValue({ error: "private server details" });

  // Act
  await click("Retry download");

  // Assert
  expect({
    hidden: document.getElementById("recovery-error").hidden,
    leaked: document
      .getElementById("recovery-error")
      .textContent.includes("private server details"),
    disabled: [...document.querySelectorAll("#recovery button")].some((button) => button.disabled),
  }).toEqual({ hidden: false, leaked: false, disabled: false });
});

test("a failed retry stays visible for 2.5 seconds through a list refresh", async () => {
  // Arrange
  vi.useFakeTimers();
  await showRecovery();
  const action = Promise.withResolvers();
  const refresh = Promise.withResolvers();
  chrome.runtime.sendMessage
    .mockReturnValueOnce(action.promise)
    .mockReturnValueOnce(refresh.promise);
  const error = document.getElementById("recovery-error");

  // Act
  document.querySelector("#recovery-list button").click();
  chrome.storage.onChanged.addListener.mock.calls[0][0]({ recoveryChangedAt: {} }, "local");
  action.resolve({ error: "Download failed" });
  await vi.advanceTimersByTimeAsync(0);
  refresh.resolve({ recordings: [recording] });
  await vi.advanceTimersByTimeAsync(2499);
  const visibleDuringRefresh = !error.hidden;
  await vi.advanceTimersByTimeAsync(1);

  // Assert
  expect({ visibleDuringRefresh, hiddenAfterTimeout: error.hidden }).toEqual({
    visibleDuringRefresh: true,
    hiddenAfterTimeout: true,
  });
});

test("discard asks for confirmation before removing the local recording", async () => {
  // Arrange
  await showRecovery();
  vi.spyOn(window, "confirm").mockReturnValue(true);
  chrome.runtime.sendMessage.mockResolvedValue({ recordings: [] });

  // Act
  await click("Discard");

  // Assert
  expect(chrome.runtime.sendMessage).toHaveBeenLastCalledWith({
    type: "recovery-discard",
    id: "one",
  });
});

test("cancelling discard keeps the recording and sends no removal command", async () => {
  // Arrange
  await showRecovery();
  vi.spyOn(window, "confirm").mockReturnValue(false);

  // Act
  [...document.querySelectorAll("#recovery button")]
    .find((button) => button.textContent === "Discard")
    .click();

  // Assert
  expect(chrome.runtime.sendMessage).toHaveBeenCalledTimes(1);
});

test("a temporary recovery copy warns that it cannot survive a restart", async () => {
  // Arrange
  chrome.runtime.sendMessage.mockResolvedValue({ recordings: [{ ...recording, temporary: true }] });

  // Act
  await showRecovery();

  // Assert
  expect(document.getElementById("recovery-list").textContent).toContain(
    "will not survive a restart",
  );
});
