function stream() {
  const track = { stop: vi.fn() };
  return { track, getTracks: () => [track] };
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

class Unsupported {
  constructor() {
    throw new Error("Not supported.");
  }
}

let port;

async function recordFailing() {
  const tab = stream();
  const microphone = stream();
  let failure = null;
  try {
    await globalThis.whadioAudio.record(tab, microphone, "recording:7:0", true);
  } catch (error) {
    failure = error.message;
  }
  return {
    failure,
    stopped: [tab.track.stop.mock.calls.length, microphone.track.stop.mock.calls.length],
  };
}

beforeEach(async () => {
  vi.resetModules();
  port = { disconnect: vi.fn(), onDisconnect: { addListener() {} } };
  vi.stubGlobal("chrome", { runtime: { connect: () => port } });
  vi.stubGlobal("whadioRecordingReady", async () => 0);
  await import("./audio.js");
});

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("a recording that fails while it is set up", () => {
  test("stops the tab and microphone tracks when the audio context cannot open", async () => {
    // Arrange
    vi.stubGlobal("AudioContext", Unsupported);

    // Act
    const result = await recordFailing();

    // Assert
    expect(result).toEqual({ failure: "Not supported.", stopped: [1, 1] });
  });

  test("stops both tracks and lets go of the port when the recorder cannot start", async () => {
    // Arrange
    vi.stubGlobal("AudioContext", FakeAudioContext);
    vi.stubGlobal("MediaRecorder", Unsupported);

    // Act
    const result = await recordFailing();

    // Assert
    expect({ ...result, disconnected: port.disconnect.mock.calls.length }).toEqual({
      failure: "Not supported.",
      stopped: [1, 1],
      disconnected: 1,
    });
  });
});

describe("a recording that ends normally", () => {
  test("stops the tab and microphone tracks when the recorder stops", async () => {
    // Arrange
    const listeners = {};
    vi.stubGlobal("AudioContext", FakeAudioContext);
    vi.stubGlobal(
      "MediaRecorder",
      class {
        addEventListener(type, listener) {
          listeners[type] = listener;
        }
        start() {}
      },
    );
    const tab = stream();
    const microphone = stream();
    await globalThis.whadioAudio.record(tab, microphone, "recording:7:0", true);

    // Act
    listeners.stop();

    // Assert
    expect([tab.track.stop.mock.calls.length, microphone.track.stop.mock.calls.length]).toEqual([
      1, 1,
    ]);
  });
});

test("waits for registration before constructing the recorder", async () => {
  // Arrange
  vi.stubGlobal("AudioContext", FakeAudioContext);
  const ready = Promise.withResolvers();
  globalThis.whadioRecordingReady = () => ready.promise;
  const construct = vi.fn();
  vi.stubGlobal(
    "MediaRecorder",
    class {
      constructor() {
        construct();
      }
      addEventListener() {}
      start() {}
    },
  );

  // Act
  const pending = globalThis.whadioAudio.record(stream(), stream(), "recording:7:0", true);
  const before = construct.mock.calls.length;
  ready.resolve(0);
  await pending;

  // Assert
  expect({ before, after: construct.mock.calls.length }).toEqual({ before: 0, after: 1 });
});

test("a rejected registration releases both tracks, context and port", async () => {
  // Arrange
  const close = vi.spyOn(FakeAudioContext.prototype, "close");
  vi.stubGlobal("AudioContext", FakeAudioContext);
  globalThis.whadioRecordingReady = async () => {
    throw new Error("Registration refused.");
  };

  // Act
  const result = await recordFailing();

  // Assert
  expect({
    ...result,
    closed: close.mock.calls.length,
    disconnected: port.disconnect.mock.calls.length,
  }).toEqual({
    failure: "Registration refused.",
    stopped: [1, 1],
    closed: 1,
    disconnected: 1,
  });
});
