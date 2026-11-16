import { setImmediate } from "node:timers/promises";

import { downloadFile } from "./downloads.js";

let listeners;

function emit(id, state) {
  for (const listener of listeners) {
    listener({ id, state: { current: state } });
  }
}

beforeEach(() => {
  listeners = new Set();
  globalThis.chrome = {
    downloads: {
      download: vi.fn(async () => 10),
      search: vi.fn(async () => [{ id: 10, state: "in_progress" }]),
      onChanged: {
        addListener: (listener) => listeners.add(listener),
        removeListener: (listener) => listeners.delete(listener),
      },
    },
  };
});

test("accepts only completion of the chosen download, ignoring unrelated downloads and progress", async () => {
  // Arrange
  let settled = false;
  const saving = downloadFile({ url: "blob:synthetic", filename: "recording.webm" }).then(() => {
    settled = true;
  });
  await Promise.resolve();

  // Act
  emit(99, "complete");
  emit(10, "in_progress");
  await setImmediate();
  const premature = settled;
  emit(10, "complete");
  await saving;

  // Assert
  expect({ premature, settled, listeners: listeners.size }).toEqual({
    premature: false,
    settled: true,
    listeners: 0,
  });
});

test("an interrupted download rejects instead of reporting a successful save", async () => {
  // Arrange
  const saving = downloadFile({});
  await Promise.resolve();

  // Act
  emit(10, "interrupted");
  const error = await saving.catch((failure) => failure.message);

  // Assert
  expect({ error, listeners: listeners.size }).toEqual({
    error: "The local download was interrupted. Retry it from Whadio.",
    listeners: 0,
  });
});

test.for(["complete", "interrupted"])(
  "handles %s arriving before download() returns its ID",
  async (state) => {
    // Arrange
    chrome.downloads.download.mockImplementation(async () => {
      chrome.downloads.search.mockResolvedValue([{ id: 10, state }]);
      emit(10, state);
      return 10;
    });

    // Act
    const result = await downloadFile({}).then(
      () => "saved",
      () => "failed",
    );

    // Assert
    expect({ result, listeners: listeners.size }).toEqual({
      result: state === "complete" ? "saved" : "failed",
      listeners: 0,
    });
  },
);

test.for(["complete", "interrupted"])(
  "reconciles an already %s download from history without waiting for another event",
  async (state) => {
    // Arrange
    chrome.downloads.search.mockResolvedValue([{ id: 10, state }]);

    // Act
    const result = await downloadFile({}).then(
      () => "saved",
      () => "failed",
    );

    // Assert
    expect({ result, listeners: listeners.size }).toEqual({
      result: state === "complete" ? "saved" : "failed",
      listeners: 0,
    });
  },
);

test.for(["download", "search"])(
  "a rejected %s API call still removes its event listener",
  async (method) => {
    // Arrange
    chrome.downloads[method].mockRejectedValue(new Error("Unavailable"));

    // Act
    const error = await downloadFile({}).catch((failure) => failure.message);

    // Assert
    expect({ error, listeners: listeners.size }).toEqual({ error: "Unavailable", listeners: 0 });
  },
);

test("a download missing from history fails rather than waiting forever", async () => {
  // Arrange
  chrome.downloads.search.mockResolvedValue([]);

  // Act
  const error = await downloadFile({}).catch((failure) => failure.message);

  // Assert
  expect({ error, listeners: listeners.size }).toEqual({
    error: "The local download is no longer available.",
    listeners: 0,
  });
});

test.for(["complete", "interrupted"])(
  "keeps a %s event received while the history lookup is pending",
  async (state) => {
    // Arrange
    const history = Promise.withResolvers();
    chrome.downloads.search.mockReturnValue(history.promise);
    const saving = downloadFile({}).then(
      () => "saved",
      () => "failed",
    );
    await setImmediate();

    // Act
    emit(10, state);
    history.resolve([{ id: 10, state: "in_progress" }]);
    const result = await saving;

    // Assert
    expect({ result, listeners: listeners.size }).toEqual({
      result: state === "complete" ? "saved" : "failed",
      listeners: 0,
    });
  },
);
