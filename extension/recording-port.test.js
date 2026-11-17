import "./recording-port.js";

function event() {
  const listeners = new Set();
  return {
    listeners,
    addListener: (listener) => listeners.add(listener),
    removeListener: (listener) => listeners.delete(listener),
  };
}

afterEach(() => vi.useRealTimers());

test.for([
  {
    reason: "timeout",
    end: async () => vi.advanceTimersByTimeAsync(5000),
    error: "Whadio did not confirm recording started.",
  },
  {
    reason: "disconnect",
    end: async (port) => port.onDisconnect.listeners.values().next().value(),
    error: "Whadio disconnected before recording started.",
  },
])("rejects and cleans up recording registration on $reason", async ({ end, error }) => {
  // Arrange
  vi.useFakeTimers();
  const port = { onMessage: event(), onDisconnect: event(), disconnect: vi.fn() };

  // Act
  const ready = globalThis.whadioRecordingReady(port).catch((failure) => failure.message);
  await end(port);
  const outcome = await ready;

  // Assert
  expect({
    outcome,
    disconnected: port.disconnect.mock.calls.length,
    remainingListeners: port.onMessage.listeners.size + port.onDisconnect.listeners.size,
    remainingTimers: vi.getTimerCount(),
  }).toEqual({ outcome: error, disconnected: 1, remainingListeners: 0, remainingTimers: 0 });
});
