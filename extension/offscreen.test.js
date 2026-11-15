describe("microphone setup", () => {
function tracks() {
  return { getTracks: () => [{ stop() {} }] };
}

function refused(name) {
  return Object.assign(new Error(name), { name });
}

async function startRefused(failureName, state) {
  vi.stubGlobal("navigator", {
    mediaDevices: {
      getUserMedia: vi
        .fn()
        .mockResolvedValueOnce(tracks())
        .mockRejectedValueOnce(refused(failureName)),
    },
    permissions: { query: async () => ({ state }) },
  });
  const listeners = [];
  vi.stubGlobal("chrome", { runtime: { getURL: (path) => `chrome-extension://whadio/${path}`, onConnect: { addListener() {} }, onMessage: { addListener: (l) => listeners.push(l) } } });
  await import("./offscreen.js");
  return new Promise((resolve) => {
    listeners[0]({ target: "offscreen", type: "record", tabId: 7, streamId: "s" }, {}, resolve);
  });
}

beforeEach(() => {
  vi.resetModules();
});

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("a microphone the offscreen document cannot open", () => {
  test.for([
    [
      "NotAllowedError",
      "prompt",
      {
        error: "Allow Whadio to use your microphone in the tab that opened, then start again.",
        microphone: true,
      },
    ],
    [
      "NotAllowedError",
      "denied",
      {
        error:
          "Whadio is blocked from your microphone. Allow it for Whadio in Chrome's site settings, then start again.",
      },
    ],
    [
      "NotAllowedError",
      "granted",
      {
        error:
          "Your system keeps Chrome from using the microphone. Allow it there, then start again.",
      },
    ],
    [
      "NotFoundError",
      "prompt",
      { error: "Whadio found no microphone. Connect one, then start again." },
    ],
  ])("%s with the permission %s answers with its message", async ([name, state, answer]) => {
    // Arrange
    const refusal = startRefused(name, state);

    // Act
    const reply = await refusal;

    // Assert
    expect(reply).toEqual(answer);
  });
});

});

import { recoveryStore } from "./recovery-store.js";

vi.mock("./recovery-store.js", () => ({ recoveryStore: { get: vi.fn() } }));

describe("recovery authorization", () => {
const worker = { url: "chrome-extension://whadio/background.js" };
const meet = { url: "https://meet.google.com/abc-defg-hij", tab: { id: 7 } };

beforeEach(async () => {
  vi.resetModules();
  recoveryStore.get.mockReset();
  vi.stubGlobal("chrome", {
    runtime: {
      getURL: (path) => `chrome-extension://whadio/${path}`,
      onConnect: { addListener: vi.fn() },
      onMessage: { addListener: vi.fn() },
    },
  });
  vi.spyOn(URL, "createObjectURL").mockReturnValue("blob:recording");
  vi.spyOn(URL, "revokeObjectURL").mockImplementation(() => {});
  await import("./offscreen.js");
});

afterEach(() => {
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
});

function send(message, sender, respond) {
  const [[listener]] = chrome.runtime.onMessage.addListener.mock.calls;
  return listener({ target: "offscreen", ...message }, sender, respond);
}

function connect(sender) {
  const [[listener]] = chrome.runtime.onConnect.addListener.mock.calls;
  const port = {
    name: "recovery-blob",
    sender,
    onMessage: { addListener: vi.fn() },
    onDisconnect: { addListener: vi.fn() },
    postMessage: vi.fn(),
  };
  listener(port);
  return port;
}

test.for([meet, { ...worker, tab: meet.tab }, { url: "chrome-extension://whadio/popup.html" }])(
  "ignores recovery messages and ports from a non-worker sender: %j",
  (sender) => {
    // Arrange
    const respond = vi.fn();

    // Act
    const blob = send({ type: "blob", id: "saved" }, sender, respond);
    const revoke = send({ type: "revoke", url: "blob:recording" }, sender, respond);
    const port = connect(sender);

    // Assert
    expect({
      blob,
      revoke,
      replies: respond.mock.calls,
      reads: recoveryStore.get.mock.calls,
      revoked: URL.revokeObjectURL.mock.calls,
      portListeners: port.onMessage.addListener.mock.calls,
    }).toEqual({
      blob: false,
      revoke: false,
      replies: [],
      reads: [],
      revoked: [],
      portListeners: [],
    });
  },
);

test("builds a stored recording's Blob and revokes it on the worker's request", async () => {
  // Arrange
  recoveryStore.get.mockResolvedValue({ slices: [btoa("stored audio")] });
  const respond = vi.fn();

  // Act
  const reply = await new Promise((resolve) =>
    send({ type: "blob", id: "saved" }, worker, resolve),
  );
  send({ type: "revoke", url: reply.url }, worker, respond);
  const [[blob]] = URL.createObjectURL.mock.calls;

  // Assert
  expect({
    reply,
    data: await blob.text(),
    type: blob.type,
    revoked: URL.revokeObjectURL.mock.calls,
    acknowledgement: respond.mock.calls,
  }).toEqual({
    reply: { url: "blob:recording" },
    data: "stored audio",
    type: "audio/webm",
    revoked: [["blob:recording"]],
    acknowledgement: [[{}]],
  });
});

test("a missing recording returns no Blob URL", async () => {
  // Arrange
  recoveryStore.get.mockResolvedValue(undefined);

  // Act
  const reply = await new Promise((resolve) =>
    send({ type: "blob", id: "missing" }, worker, resolve),
  );

  // Assert
  expect({ reply, blobs: URL.createObjectURL.mock.calls }).toEqual({ reply: {}, blobs: [] });
});

test("the worker's recovery port combines temporary chunks into a Blob", async () => {
  // Arrange
  const port = connect(worker);
  const [[receive]] = port.onMessage.addListener.mock.calls;

  // Act
  receive({ chunk: btoa("temporary ") });
  receive({ chunk: btoa("audio") });
  receive({ complete: true });
  const [[blob]] = URL.createObjectURL.mock.calls;

  // Assert
  expect({ replies: port.postMessage.mock.calls, data: await blob.text() }).toEqual({
    replies: [[{ accepted: true }], [{ accepted: true }], [{ url: "blob:recording" }]],
    data: "temporary audio",
  });
});

});
