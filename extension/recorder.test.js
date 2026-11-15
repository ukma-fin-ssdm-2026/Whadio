// @vitest-environment jsdom

let root;

function event() {
  const listeners = [];
  return {
    listeners,
    addListener: (listener) => listeners.push(listener),
    removeListener: (listener) => listeners.splice(listeners.indexOf(listener), 1),
  };
}

function port() {
  return { onDisconnect: event(), disconnect: vi.fn() };
}

function fakeChrome({ signedIn = true, unreachable = false } = {}) {
  return {
    runtime: {
      onMessage: event(),
      connect: vi.fn(() => port()),
      sendMessage: vi.fn(async (message) => {
        if (message.type !== "signed-in") {
          return undefined;
        }
        if (unreachable) {
          throw new Error("Extension context invalidated.");
        }
        return signedIn;
      }),
    },
    storage: {
      local: { get: async () => ({}), set: async () => {} },
      onChanged: event(),
    },
  };
}

async function load(options) {
  globalThis.chrome = fakeChrome(options);
  await import("./recording-port.js");
  await import("./audio.js");
  await import("./recorder.js");
}

function audioStream() {
  const track = { stop: vi.fn(), addEventListener: vi.fn() };
  return {
    track,
    getTracks: () => [track],
    getAudioTracks: () => [track],
    getVideoTracks: () => [],
  };
}

class FakeRecorder {
  static last = null;
  state = "inactive";
  listeners = [];
  constructor() {
    FakeRecorder.last = this;
  }
  addEventListener(type, listener) {
    this.listeners.push([type, listener]);
  }
  start() {
    this.state = "recording";
  }
  stop() {
    this.state = "inactive";
    this.emit("stop");
  }
  emit(type) {
    for (const [name, listener] of this.listeners) {
      if (name === type) {
        listener();
      }
    }
  }
}

class FakeAudioContext {
  createMediaStreamDestination() {
    return { stream: {} };
  }
  createMediaStreamSource() {
    return { connect() {} };
  }
  async close() {}
}

function fakeMedia() {
  const tab = audioStream();
  const microphone = audioStream();
  let openMicrophone;
  vi.stubGlobal("AudioContext", FakeAudioContext);
  vi.stubGlobal("MediaRecorder", FakeRecorder);
  vi.stubGlobal("navigator", {
    mediaDevices: {
      getDisplayMedia: async () => tab,
      getUserMedia: () =>
        new Promise((resolve) => {
          openMicrophone = () => resolve(microphone);
        }),
    },
  });
  return { tab, microphone, openMicrophone: () => openMicrophone() };
}

async function pressStart() {
  const consent = root.querySelector('input[type="checkbox"]');
  consent.checked = true;
  consent.dispatchEvent(new Event("change"));
  root.querySelector("button.primary").click();
  await vi.advanceTimersByTimeAsync(0);
}

function send(message) {
  const sendResponse = vi.fn();
  chrome.runtime.onMessage.listeners[0](message, {}, sendResponse);
  return sendResponse;
}

function cardShown() {
  return root.host.isConnected;
}

function cardError() {
  const error = root.querySelector(".error");
  return error.hidden ? null : error.textContent;
}

function panelShown() {
  return [...root.querySelectorAll("h2")].find((title) => !title.parentElement.hidden)?.textContent;
}

function sentTypes() {
  return chrome.runtime.sendMessage.mock.calls.map(([message]) => message.type);
}

function joinCall() {
  document.body.append(
    Object.assign(document.createElement("button"), { textContent: "call_end" }),
  );
}

function speaking(name) {
  const tile = document.createElement("div");
  tile.dataset.participantId = name;
  const label = Object.assign(document.createElement("span"), { className: "notranslate" });
  label.textContent = name;
  const level = document.createElement("div");
  level.setAttribute("jsname", "QgSmzd");
  tile.append(label, level);
  document.body.append(tile);
}

function speakersSent() {
  return chrome.runtime.sendMessage.mock.calls
    .map(([message]) => message)
    .filter((message) => message.type === "speakers")
    .map((message) => message.speakers);
}

beforeEach(() => {
  vi.useFakeTimers();
  vi.resetModules();
  document.body.replaceChildren();
  delete globalThis.whadioRecorder;
  const attachShadow = Element.prototype.attachShadow;
  vi.spyOn(Element.prototype, "attachShadow").mockImplementation(function (init) {
    root = attachShadow.call(this, init);
    return root;
  });
});

afterEach(() => {
  vi.clearAllTimers();
  vi.useRealTimers();
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
});

function stubPickedCapture() {
  const tabTrack = { stop: vi.fn(), addEventListener: vi.fn() };
  const microphoneTrack = { stop: vi.fn() };
  const tab = {
    getVideoTracks: () => [],
    getAudioTracks: () => [tabTrack],
    getTracks: () => [tabTrack],
  };
  const close = vi.fn(async () => {});
  const createSource = () => ({ connect() {} });
  vi.stubGlobal("navigator", {
    mediaDevices: {
      getDisplayMedia: async () => tab,
      getUserMedia: async () => ({ getTracks: () => [microphoneTrack] }),
    },
  });
  vi.stubGlobal(
    "AudioContext",
    class {
      createMediaStreamDestination = () => ({});
      createMediaStreamSource = createSource;
      close = close;
    },
  );
  const port = { onMessage: event(), onDisconnect: event(), disconnect: vi.fn() };
  chrome.runtime.connect.mockReturnValue(port);
  return { tabTrack, microphoneTrack, close, port };
}

test("a rejected recording port releases the picked tab and microphone without starting", async () => {
  // Arrange
  await load();
  const { tabTrack, microphoneTrack, close, port } = stubPickedCapture();
  const createRecorder = vi.fn();
  vi.stubGlobal("MediaRecorder", createRecorder);

  // Act
  root.querySelector("button.primary").disabled = false;
  root.querySelector("button.primary").click();
  await vi.waitFor(() => expect(port.onMessage.listeners).toHaveLength(1));
  const startedBeforeReply = createRecorder.mock.calls.length;
  port.onMessage.listeners[0]({
    type: "recording-rejected",
    error: "Sign in to Whadio before recording.",
  });
  await vi.waitFor(() => expect(cardError()).toBe("Sign in to Whadio before recording."));

  // Assert
  expect({
    startedBeforeReply,
    totalStarts: createRecorder.mock.calls.length,
    tabStopped: tabTrack.stop.mock.calls.length,
    microphoneStopped: microphoneTrack.stop.mock.calls.length,
    audioClosed: close.mock.calls.length,
  }).toEqual({
    startedBeforeReply: 0,
    totalStarts: 0,
    tabStopped: 1,
    microphoneStopped: 1,
    audioClosed: 1,
  });
});

test("disconnecting the recording port stops the recorder and releases both audio tracks", async () => {
  // Arrange
  await load();
  const { tabTrack, microphoneTrack, close, port } = stubPickedCapture();
  const start = vi.fn();
  const stop = vi.fn();
  vi.stubGlobal(
    "MediaRecorder",
    class {
      addEventListener = vi.fn();
      start = start;
      stop = stop;
    },
  );
  root.querySelector("button.primary").disabled = false;
  root.querySelector("button.primary").click();
  await vi.waitFor(() => expect(port.onMessage.listeners).toHaveLength(1));
  port.onMessage.listeners[0]({ type: "recording-ready", startedAt: 1 });
  await vi.waitFor(() => expect(start).toHaveBeenCalledOnce());

  // Act
  for (const listener of port.onDisconnect.listeners) {
    listener();
  }

  // Assert
  expect({
    stopped: stop.mock.calls.length,
    tabReleased: tabTrack.stop.mock.calls.length,
    microphoneReleased: microphoneTrack.stop.mock.calls.length,
    contextClosed: close.mock.calls.length,
  }).toEqual({ stopped: 1, tabReleased: 1, microphoneReleased: 1, contextClosed: 1 });
});

describe("the recorder's answers to the extension", () => {
  test("reports no consent before the box is ticked", async () => {
    // Arrange
    await load();

    // Act
    const sendResponse = send({ type: "status" });

    // Assert
    expect(sendResponse).toHaveBeenCalledWith({ consented: false });
  });

  test("reports consent once the box is ticked", async () => {
    // Arrange
    await load();
    root.querySelector('input[type="checkbox"]').checked = true;

    // Act
    const sendResponse = send({ type: "status" });

    // Assert
    expect(sendResponse).toHaveBeenCalledWith({ consented: true });
  });

  test("hides the card and keeps it away for the rest of the call", async () => {
    // Arrange
    await load();
    joinCall();
    await vi.advanceTimersByTimeAsync(1000);

    // Act
    send({ type: "hide-card" });
    await vi.advanceTimersByTimeAsync(3000);

    // Assert
    expect(cardShown()).toBe(false);
  });

  test("shows the sign-in card when asked to, even after it was dismissed", async () => {
    // Arrange
    await load({ signedIn: false });
    send({ type: "hide-card" });

    // Act
    send({ type: "ask-sign-in" });
    await vi.advanceTimersByTimeAsync(0);

    // Assert
    expect([cardShown(), panelShown()]).toEqual([true, "Sign in to Whadio"]);
  });

  test("shows the card with a hint to tick the box when consent is missing", async () => {
    // Arrange
    await load();

    // Act
    send({ type: "ask-consent" });
    await vi.advanceTimersByTimeAsync(0);

    // Assert
    expect([cardShown(), cardError()]).toEqual([
      true,
      "Tick the box first, then press Alt+Shift+R again.",
    ]);
  });

  test("shows nothing when the extension is unreachable as consent is asked for", async () => {
    // Arrange
    await load({ unreachable: true });

    // Act
    send({ type: "ask-consent" });
    await vi.advanceTimersByTimeAsync(0);

    // Assert
    expect(cardShown()).toBe(false);
  });

  test("shows nothing when the extension is unreachable as sign-in is asked for", async () => {
    // Arrange
    await load({ unreachable: true });

    // Act
    send({ type: "ask-sign-in" });
    await vi.advanceTimersByTimeAsync(0);

    // Assert
    expect(cardShown()).toBe(false);
  });

  test("shows an error on the card without asking whether the user is signed in", async () => {
    // Arrange
    await load();

    // Act
    send({ type: "show-error", error: "The server is unreachable." });

    // Assert
    expect([cardShown(), cardError(), sentTypes()]).toEqual([
      true,
      "The server is unreachable.",
      [],
    ]);
  });

  test("holds a page port while a recording runs in the offscreen document", async () => {
    // Arrange
    await load();

    // Act
    send({ type: "started", startedAt: 0 });

    // Assert
    expect(chrome.runtime.connect).toHaveBeenCalledWith({ name: "page" });
  });

  test("sends the speakers of the second when asked to flush them", async () => {
    // Arrange
    await load();
    speaking("Zoe");
    send({ type: "started", startedAt: 0 });
    await vi.advanceTimersByTimeAsync(250);

    // Act
    send({ type: "flush-speakers" });

    // Assert
    expect(speakersSent()).toEqual([["Zoe"]]);
  });

  test("sends the speakers of each second sorted by their code units", async () => {
    // Arrange
    await load();
    for (const name of ["Олена", "anna", "Zoe", "Émile"]) {
      speaking(name);
    }
    send({ type: "started", startedAt: 0 });

    // Act
    await vi.advanceTimersByTimeAsync(1000);

    // Assert
    expect(speakersSent()).toEqual([["Zoe", "anna", "Émile", "Олена"]]);
  });

  test("sends the speakers once a second has passed even when its timer runs late", async () => {
    // Arrange
    await load();
    speaking("Zoe");
    send({ type: "started", startedAt: 0 });
    vi.spyOn(performance, "now").mockReturnValue(performance.now() + 1000);

    // Act
    await vi.advanceTimersByTimeAsync(250);

    // Assert
    expect(speakersSent()).toEqual([["Zoe"]]);
  });

  test("ends the recording reported as stopped, so its speakers are no longer sent", async () => {
    // Arrange
    await load();
    speaking("Zoe");
    send({ type: "started", startedAt: 5 });

    // Act
    send({ type: "stopped", startedAt: 5 });
    await vi.advanceTimersByTimeAsync(1000);

    // Assert
    expect(speakersSent()).toEqual([]);
  });

  test("keeps its recording when an older one is reported as stopped", async () => {
    // Arrange
    await load();
    speaking("Zoe");
    send({ type: "started", startedAt: 5 });

    // Act
    send({ type: "stopped", startedAt: 0 });
    await vi.advanceTimersByTimeAsync(1000);

    // Assert
    expect(speakersSent()).toEqual([["Zoe"]]);
  });

  test("answers that it took a recording reported as started", async () => {
    // Arrange
    await load();

    // Act
    const sendResponse = send({ type: "started", startedAt: 0 });

    // Assert
    expect(sendResponse).toHaveBeenCalledWith({ taken: true });
  });

  test("answers that it did not take a second recording reported as started", async () => {
    // Arrange
    await load();
    send({ type: "started", startedAt: 0 });

    // Act
    const sendResponse = send({ type: "started", startedAt: 5 });

    // Assert
    expect(sendResponse).toHaveBeenCalledWith({ taken: false });
  });

  test("accepts a new recording once the page port of the last one disconnects", async () => {
    // Arrange
    await load();
    send({ type: "started", startedAt: 0 });
    chrome.runtime.connect.mock.results[0].value.onDisconnect.listeners[0]();

    // Act
    send({ type: "started", startedAt: 5 });

    // Assert
    expect(chrome.runtime.connect.mock.calls).toEqual([[{ name: "page" }], [{ name: "page" }]]);
  });

  test("accepts a new recording once the recorder of the card stops on its own", async () => {
    // Arrange
    await load();
    const media = fakeMedia();
    await pressStart();
    media.openMicrophone();
    await vi.advanceTimersByTimeAsync(0);
    FakeRecorder.last.stop();

    // Act
    send({ type: "started", startedAt: 5 });

    // Assert
    expect(chrome.runtime.connect.mock.calls.at(-1)).toEqual([{ name: "page" }]);
  });

  test("refuses the card's recording when another one began while the microphone opened", async () => {
    // Arrange
    await load();
    const media = fakeMedia();
    await pressStart();
    send({ type: "started", startedAt: 5 });

    // Act
    media.openMicrophone();
    await vi.advanceTimersByTimeAsync(0);

    // Assert
    expect([cardError(), chrome.runtime.connect.mock.calls]).toEqual([
      "Whadio is already recording this call.",
      [[{ name: "page" }]],
    ]);
  });

  test("stops the tab and microphone tracks of a card recording that was refused", async () => {
    // Arrange
    await load();
    const media = fakeMedia();
    await pressStart();
    send({ type: "started", startedAt: 5 });

    // Act
    media.openMicrophone();
    await vi.advanceTimersByTimeAsync(0);

    // Assert
    expect([
      media.tab.track.stop.mock.calls.length,
      media.microphone.track.stop.mock.calls.length,
    ]).toEqual([1, 1]);
  });

  test("keeps the running recording when another one is reported as started", async () => {
    // Arrange
    await load();
    send({ type: "started", startedAt: 0 });

    // Act
    send({ type: "started", startedAt: 5 });

    // Assert
    expect(chrome.runtime.connect.mock.calls).toEqual([[{ name: "page" }]]);
  });

  test("asks the background to stop the recording and answers when told to stop", async () => {
    // Arrange
    await load();
    send({ type: "started", startedAt: 0 });

    // Act
    const sendResponse = send({ type: "stop" });

    // Assert
    expect([sentTypes(), sendResponse.mock.calls]).toEqual([["stop-recording"], [[{}]]]);
  });

  test("answers a stop without a recording and stops nothing", async () => {
    // Arrange
    await load();

    // Act
    const sendResponse = send({ type: "stop" });

    // Assert
    expect([sentTypes(), sendResponse.mock.calls]).toEqual([[], [[{}]]]);
  });

  test("ignores a message it does not know", async () => {
    // Arrange
    await load();

    // Act
    const sendResponse = send({ type: "toString" });

    // Assert
    expect([sentTypes(), sendResponse.mock.calls, cardShown()]).toEqual([[], [], false]);
  });
});
