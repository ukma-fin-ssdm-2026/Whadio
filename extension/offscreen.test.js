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
    ["NotAllowedError", "prompt", true],
    ["NotAllowedError", "denied", false],
    ["NotAllowedError", "granted", false],
    ["NotFoundError", "prompt", false],
  ])("%s with the permission %s asks for the microphone page: %s", async ([name, state, page]) => {
    // Arrange
    const refusal = startRefused(name, state);

    // Act
    const reply = await refusal;

    // Assert
    expect(reply.microphone === true).toBe(page);
  });
});
