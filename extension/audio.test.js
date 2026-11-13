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

function recordFailing() {
  const tab = stream();
  const microphone = stream();
  let failure = null;
  try {
    globalThis.whadioAudio.record(tab, microphone, "recording:7:0", true);
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
  await import("./audio.js");
});

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("a recording that fails while it is set up", () => {
  test("stops the tab and microphone tracks when the audio context cannot open", () => {
    // Arrange
    vi.stubGlobal("AudioContext", Unsupported);

    // Act
    const result = recordFailing();

    // Assert
    expect(result).toEqual({ failure: "Not supported.", stopped: [1, 1] });
  });

  test("stops both tracks and lets go of the port when the recorder cannot start", () => {
    // Arrange
    vi.stubGlobal("AudioContext", FakeAudioContext);
    vi.stubGlobal("MediaRecorder", Unsupported);

    // Act
    const result = recordFailing();

    // Assert
    expect({ ...result, disconnected: port.disconnect.mock.calls.length }).toEqual({
      failure: "Not supported.",
      stopped: [1, 1],
      disconnected: 1,
    });
  });
});
