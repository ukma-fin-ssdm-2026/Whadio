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
  vi.stubGlobal("chrome", { runtime: { onMessage: { addListener: (l) => listeners.push(l) } } });
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
