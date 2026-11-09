import { TIMEOUT_MS } from "./api.js";
import { recoveryStore } from "./recovery-store.js";

vi.mock("./recovery-store.js", () => {
  const recordings = new Map();
  return {
    recoveryStore: {
      put: vi.fn(async (recording) => recordings.set(recording.id, structuredClone(recording))),
      remove: vi.fn(async (id) => recordings.delete(id)),
      get: vi.fn(async (id) => recordings.get(id)),
      list: vi.fn(async () =>
        [...recordings.values()].map(({ id, startedAt, owner }) => ({ id, startedAt, owner })),
      ),
    },
  };
});

const SERVER = "https://whadio.example";
const DESTINATION = { workspace_id: "w1", folder_id: "f1" };
const STARTED_AT = new Date("2026-11-03T10:00:00Z");

function event() {
  const listeners = [];
  return { listeners, addListener: (listener) => listeners.push(listener), removeListener() {} };
}

function fakeChrome() {
  const downloadsChanged = event();
  return {
    runtime: {
      getURL: (path) => `chrome-extension://whadio/${path}`,
      onConnect: event(),
      onInstalled: event(),
      onMessage: event(),
      sendMessage: vi.fn(async (message) => (message.type === "blob" ? { url: "blob:call" } : {})),
    },
    storage: {
      onChanged: event(),
      session: {
        get: async () => ({
          server: SERVER,
          userId: "original",
          token: "t",
          expiresAt: "2026-11-04T10:00:00Z",
        }),
        set: async () => {},
        remove: async () => {},
        onChanged: event(),
      },
      local: { get: async () => ({ destination: DESTINATION }), set: async () => {} },
    },
    tabs: { sendMessage: vi.fn(async () => {}) },
    action: { setBadgeText: vi.fn(async () => {}) },
    commands: { onCommand: event() },
    offscreen: {
      hasDocument: vi.fn(async () => false),
      createDocument: vi.fn(async () => {}),
      closeDocument: vi.fn(async () => {}),
    },
    downloads: {
      download: vi.fn(async () => 1),
      onChanged: {
        ...downloadsChanged,
        addListener: (listener) => listener({ id: 1, state: { current: "complete" } }),
      },
    },
  };
}

function json(status, body) {
  return new Response(JSON.stringify(body), { status });
}

function answer(request) {
  if (request.method === "POST" && request.path === "/captures") {
    return json(201, { id: "c1" });
  }
  if (request.method === "GET") {
    return json(200, { received_seqs: [] });
  }
  return new Response(null, { status: 204 });
}

function read(body) {
  if (body instanceof FormData) {
    const audio = body.get("audio");
    return {
      audio: audio.name,
      bytes: audio.size,
      speakers: JSON.parse(body.get("speaker_events")),
    };
  }
  return body === undefined ? undefined : JSON.parse(body);
}

// Records every request and answers it with `reply`, which sees the request, how many like it came before
// and the request's abort signal.
function fakeServer(reply = answer) {
  const requests = [];
  globalThis.fetch = vi.fn(async (url, init) => {
    const request = {
      method: init.method,
      path: url.slice(`${SERVER}/api/v1`.length),
      body: read(init.body),
      at: Date.now() - STARTED_AT.getTime(),
    };
    const earlier = requests.filter((r) => r.method === request.method && r.path === request.path);
    requests.push(request);
    return reply(request, earlier.length, init.signal);
  });
  return requests;
}

function failingPuts(failures, failure = () => new Response(null, { status: 503 })) {
  return (request, earlier) =>
    request.method === "PUT" && earlier < failures ? failure() : answer(request);
}

// Answers after `delay`, unless the request's deadline aborts it first; an infinite delay never answers.
function answerAfter(delay, signal, response) {
  return new Promise((resolve, reject) => {
    const timer = Number.isFinite(delay) ? setTimeout(() => resolve(response), delay) : null;
    signal?.addEventListener("abort", () => {
      clearTimeout(timer);
      reject(signal.reason);
    });
  });
}

function port(tabId = 7) {
  return {
    name: `recording:${tabId}`,
    onMessage: event(),
    onDisconnect: event(),
    postMessage: vi.fn(),
  };
}

async function connect(tabId = 7) {
  const recording = port(tabId);
  await chrome.runtime.onConnect.listeners[0](recording);
  return recording;
}

function speak(recording, slices) {
  for (let slice = 0; slice < slices; slice += 1) {
    recording.onMessage.listeners[0]({ audio: btoa("ab") });
  }
}

function hear(at, speakers) {
  for (const listener of chrome.runtime.onMessage.listeners) {
    listener({ type: "speakers", at, speakers }, { tab: { id: 7 } });
  }
}

async function hangUp(recording) {
  const finished = Promise.all(recording.onDisconnect.listeners.map((listener) => listener()));
  await vi.runAllTimersAsync();
  await finished;
}

function sent(requests, method) {
  return requests.filter((request) => request.method === method).map((request) => request.path);
}

beforeEach(async () => {
  vi.useFakeTimers({ now: STARTED_AT });
  vi.resetModules();
  vi.restoreAllMocks();
  for (const { id } of await recoveryStore.list()) {
    await recoveryStore.remove(id);
  }
  vi.clearAllMocks();
  globalThis.chrome = fakeChrome();
  await import("./background.js");
});

afterEach(() => {
  vi.useRealTimers();
  vi.restoreAllMocks();
});

function recover(message, sender = { url: "chrome-extension://whadio/popup.html" }) {
  return new Promise((resolve) => {
    for (const listener of chrome.runtime.onMessage.listeners) {
      listener(message, sender, resolve);
    }
  });
}

describe("recording registration", () => {
  test("rejects a port when the session has expired", async () => {
    // Arrange
    chrome.storage.session.get = async () => ({ expiresAt: STARTED_AT.toISOString() });
    const requests = fakeServer();

    // Act
    const recording = await connect();

    // Assert
    expect({
      replies: recording.postMessage.mock.calls,
      requests,
    }).toEqual({
      replies: [[{ type: "recording-rejected", error: "Sign in to Whadio before recording." }]],
      requests: [],
    });
  });

  test("ignores a port that disconnects while the session is being read", async () => {
    // Arrange
    const session = await chrome.storage.session.get();
    const { promise, resolve } = Promise.withResolvers();
    chrome.storage.session.get = () => promise;
    const requests = fakeServer();
    const recording = port();

    // Act
    const connecting = chrome.runtime.onConnect.listeners[0](recording);
    await hangUp(recording);
    resolve(session);
    await connecting;

    // Assert
    expect({
      replies: recording.postMessage.mock.calls,
      recordingBadge: chrome.action.setBadgeText.mock.calls.some(([badge]) => badge.text === "REC"),
      requests,
    }).toEqual({ replies: [], recordingBadge: false, requests: [] });
  });
});

describe("a recording whose local save fails", () => {
  async function failSaving() {
    fakeServer(failingPuts(Number.POSITIVE_INFINITY));
    chrome.downloads.download.mockRejectedValue(new Error("private details"));
    const recording = await connect();
    speak(recording, 15);
    await hangUp(recording);
  }

  test("waits for the recovery transaction to commit before attempting the fallback download", async () => {
    // Arrange
    fakeServer(failingPuts(Number.POSITIVE_INFINITY));
    const { promise, resolve } = Promise.withResolvers();
    const put = recoveryStore.put.getMockImplementation();
    recoveryStore.put.mockImplementationOnce(async (recording) => {
      await promise;
      await put(recording);
    });
    const recording = await connect();
    speak(recording, 15);

    // Act
    await hangUp(recording);
    const beforeCommit = {
      writes: recoveryStore.put.mock.calls.length,
      downloads: chrome.downloads.download.mock.calls.length,
    };
    resolve();
    await vi.runAllTimersAsync();

    // Assert
    expect({ beforeCommit, afterCommit: chrome.downloads.download.mock.calls.length }).toEqual({
      beforeCommit: { writes: 1, downloads: 0 },
      afterCommit: 1,
    });
  });

  test("retains the full recording after a download fails without an unhandled rejection", async () => {
    // Arrange
    vi.spyOn(console, "warn").mockImplementation(() => {});

    // Act
    await failSaving();
    const [recording] = await recoveryStore.list();

    // Assert
    expect((await recoveryStore.get(recording.id)).slices).toHaveLength(15);
  });

  test.for([
    {},
    { server: SERVER, userId: "other", token: "t", expiresAt: "2026-11-04T10:00:00Z" },
    {
      server: "https://other.example",
      userId: "original",
      token: "t",
      expiresAt: "2026-11-04T10:00:00Z",
    },
    { server: SERVER, userId: "original", token: "t", expiresAt: STARTED_AT.toISOString() },
  ])(
    "refuses recovery commands for a signed-out, different or expired account: %j",
    async (session) => {
      // Arrange
      vi.spyOn(console, "warn").mockImplementation(() => {});
      await failSaving();
      const [recording] = await recoveryStore.list();
      chrome.downloads.download.mockClear();
      chrome.storage.session.get = async () => session;

      // Act
      const listed = await recover({ type: "recovery-list" });
      await recover({ type: "recovery-retry", id: recording.id });
      await recover({ type: "recovery-discard", id: recording.id });

      // Assert
      expect({
        visible: listed.recordings,
        downloads: chrome.downloads.download.mock.calls.length,
        kept: (await recoveryStore.list()).length,
      }).toEqual({ visible: [], downloads: 0, kept: 1 });
    },
  );

  test("warns on the Meet card and the toolbar without logging raw failure details", async () => {
    // Arrange
    const warning = vi.spyOn(console, "warn").mockImplementation(() => {});

    // Act
    await failSaving();

    // Assert
    expect({
      badge: chrome.action.setBadgeText.mock.calls.some(([value]) => value.text === "!"),
      card: chrome.tabs.sendMessage.mock.calls.some(([, value]) => value.type === "show-error"),
      leaked: JSON.stringify(warning.mock.calls).includes("private details"),
    }).toEqual({ badge: true, card: true, leaked: false });
  });

  test("still cleans up when both the local save and notification to a closed tab fail", async () => {
    // Arrange
    vi.spyOn(console, "warn").mockImplementation(() => {});
    chrome.offscreen.hasDocument.mockResolvedValue(true);
    chrome.tabs.sendMessage.mockRejectedValue(new Error("Tab closed"));

    // Act
    await failSaving();

    // Assert
    expect(chrome.offscreen.closeDocument).toHaveBeenCalledOnce();
  });

  test("a failed save cannot close the offscreen document while another tab is recording", async () => {
    // Arrange
    vi.spyOn(console, "warn").mockImplementation(() => {});
    fakeServer(failingPuts(Number.POSITIVE_INFINITY));
    chrome.offscreen.hasDocument.mockResolvedValue(true);
    chrome.downloads.download.mockRejectedValue(new Error("Disk unavailable"));
    const first = await connect(7);
    await connect(8);
    speak(first, 15);

    // Act
    await hangUp(first);

    // Assert
    expect(chrome.offscreen.closeDocument).not.toHaveBeenCalled();
  });

  test("retains the recording if the offscreen document cannot prepare a Blob", async () => {
    // Arrange
    vi.spyOn(console, "warn").mockImplementation(() => {});
    chrome.runtime.sendMessage.mockImplementation(async (message) => {
      if (message.type === "blob") {
        throw new Error("Offscreen document unavailable");
      }
      return {};
    });

    // Act
    await failSaving();

    // Assert
    expect(await recoveryStore.list()).toHaveLength(1);
  });

  test("keeps the backup and refuses to download a malformed Blob reply", async () => {
    // Arrange
    vi.spyOn(console, "warn").mockImplementation(() => {});
    chrome.runtime.sendMessage.mockResolvedValue({ url: "https://whadio.example/invalid" });

    // Act
    await failSaving();

    // Assert
    expect({
      copies: (await recoveryStore.list()).length,
      downloads: chrome.downloads.download.mock.calls.length,
    }).toEqual({ copies: 1, downloads: 0 });
  });

  test("revokes the Blob URL after a download fails while another tab keeps offscreen alive", async () => {
    // Arrange
    vi.spyOn(console, "warn").mockImplementation(() => {});
    await connect(8);

    // Act
    await failSaving();

    // Assert
    expect({
      revocations: chrome.runtime.sendMessage.mock.calls
        .map(([message]) => message)
        .filter((message) => message.type === "revoke"),
      copies: (await recoveryStore.list()).length,
      closes: chrome.offscreen.closeDocument.mock.calls.length,
    }).toEqual({
      revocations: [{ target: "offscreen", type: "revoke", url: "blob:call" }],
      copies: 1,
      closes: 0,
    });
  });

  test("recovers after a worker restart, retries without server access and removes the local copy", async () => {
    // Arrange
    vi.spyOn(console, "warn").mockImplementation(() => {});
    await failSaving();
    vi.resetModules();
    globalThis.chrome = fakeChrome();
    globalThis.fetch = vi.fn(() => {
      throw new Error("Server offline");
    });
    await import("./background.js");
    const {
      recordings: [recording],
    } = await recover({ type: "recovery-list" });

    // Act
    const result = await recover({ type: "recovery-retry", id: recording.id });

    // Assert
    expect({ result, downloads: chrome.downloads.download.mock.calls.length }).toEqual({
      result: { recordings: [] },
      downloads: 1,
    });
  });

  test("discards a retained recording without downloading it", async () => {
    // Arrange
    vi.spyOn(console, "warn").mockImplementation(() => {});
    await failSaving();
    const [recording] = await recoveryStore.list();
    chrome.downloads.download.mockClear();

    // Act
    const result = await recover({ type: "recovery-discard", id: recording.id });

    // Assert
    expect({ result, downloads: chrome.downloads.download.mock.calls.length }).toEqual({
      result: { recordings: [] },
      downloads: 0,
    });
  });

  test("refuses recovery commands from a Meet content script", async () => {
    // Arrange
    vi.spyOn(console, "warn").mockImplementation(() => {});
    await failSaving();
    const [recording] = await recoveryStore.list();

    // Act
    await recover(
      { type: "recovery-discard", id: recording.id },
      {
        url: "https://meet.google.com/abc-defg-hij",
        tab: { id: 7 },
      },
    );

    // Assert
    expect(await recoveryStore.list()).toHaveLength(1);
  });
});

describe("a recording's upload", () => {
  test("opens a capture for the chosen destination before any audio arrives", async () => {
    // Arrange
    const requests = fakeServer();

    // Act
    await connect();
    await vi.runAllTimersAsync();

    // Assert
    expect(requests.map(({ method, path, body }) => ({ method, path, body }))).toEqual([
      { method: "POST", path: "/captures", body: { ...DESTINATION, consent_confirmed: true } },
    ]);
  });

  test("uploads nothing while only ten slices have arrived", async () => {
    // Arrange
    const requests = fakeServer();
    const recording = await connect();

    // Act
    speak(recording, 10);
    await vi.runAllTimersAsync();

    // Assert
    expect(sent(requests, "PUT")).toEqual([]);
  });

  test("uploads every ten slices as a chunk once the slice after them arrives", async () => {
    // Arrange
    const requests = fakeServer();
    const recording = await connect();

    // Act
    speak(recording, 21);
    await vi.runAllTimersAsync();

    // Assert
    expect(requests.filter((r) => r.method === "PUT").map((r) => r.body)).toEqual([
      { audio: "0.webm", bytes: 20, speakers: [] },
      { audio: "1.webm", bytes: 20, speakers: [] },
    ]);
  });

  test("sends the speakers heard before a chunk is cut with that chunk", async () => {
    // Arrange
    const requests = fakeServer();
    const recording = await connect();
    hear(3, ["Олена", "Zoe"]);

    // Act
    speak(recording, 11);
    await vi.runAllTimersAsync();

    // Assert
    expect(requests.find((r) => r.method === "PUT").body.speakers).toEqual([
      { at_seconds: 3, speakers: ["Олена", "Zoe"] },
    ]);
  });

  test("uploads the rest and completes the capture with the last chunk's number on hang-up", async () => {
    // Arrange
    const requests = fakeServer();
    const recording = await connect();
    speak(recording, 15);

    // Act
    await hangUp(recording);

    // Assert
    expect(requests.map(({ method, path, body }) => [method, path, body?.bytes ?? body])).toEqual([
      ["POST", "/captures", { ...DESTINATION, consent_confirmed: true }],
      ["PUT", "/captures/c1/chunks/0", 20],
      ["PUT", "/captures/c1/chunks/1", 10],
      ["POST", "/captures/c1/complete", { last_seq: 1 }],
    ]);
  });

  test("retries a failed chunk after one, two and then four seconds", async () => {
    // Arrange
    const requests = fakeServer(failingPuts(3));
    const recording = await connect();

    // Act
    speak(recording, 11);
    await vi.runAllTimersAsync();

    // Assert
    expect(requests.filter((r) => r.method === "PUT").map((r) => r.at)).toEqual([
      0, 1000, 3000, 7000,
    ]);
  });

  test("asks which chunks the server holds before each retry", async () => {
    // Arrange
    const requests = fakeServer(failingPuts(2));
    const recording = await connect();

    // Act
    speak(recording, 11);
    await vi.runAllTimersAsync();

    // Assert
    expect(requests.slice(1).map((r) => `${r.method} ${r.path}`)).toEqual([
      "PUT /captures/c1/chunks/0",
      "GET /captures/c1",
      "PUT /captures/c1/chunks/0",
      "GET /captures/c1",
      "PUT /captures/c1/chunks/0",
    ]);
  });

  test("skips a chunk the server already holds after its answer was lost", async () => {
    // Arrange
    const lost = (request, earlier) => {
      if (request.method === "PUT" && request.path.endsWith("/0") && earlier === 0) {
        throw new TypeError("Failed to fetch");
      }
      return request.method === "GET" ? json(200, { received_seqs: [0] }) : answer(request);
    };
    const requests = fakeServer(lost);
    const recording = await connect();

    // Act
    speak(recording, 11);
    await hangUp(recording);

    // Assert
    expect(sent(requests, "PUT")).toEqual(["/captures/c1/chunks/0", "/captures/c1/chunks/1"]);
  });

  test("keeps retrying when the server cannot say which chunks it holds", async () => {
    // Arrange
    const unknown = (request, earlier) => {
      if (request.method === "GET") {
        return new Response(null, { status: 500 });
      }
      return failingPuts(1)(request, earlier);
    };
    const requests = fakeServer(unknown);
    const recording = await connect();

    // Act
    speak(recording, 11);
    await vi.runAllTimersAsync();

    // Assert
    expect(sent(requests, "PUT")).toEqual(["/captures/c1/chunks/0", "/captures/c1/chunks/0"]);
  });

  test("tries a failing chunk five times in all", async () => {
    // Arrange
    const requests = fakeServer(failingPuts(Number.POSITIVE_INFINITY));
    const recording = await connect();

    // Act
    speak(recording, 11);
    await vi.runAllTimersAsync();

    // Assert
    expect(sent(requests, "PUT")).toHaveLength(5);
  });

  test.for([401, 404])("stops at once when the server answers %i", async (status) => {
    // Arrange
    const requests = fakeServer(failingPuts(1, () => new Response(null, { status })));
    const recording = await connect();

    // Act
    speak(recording, 11);
    await vi.runAllTimersAsync();

    // Assert
    expect(sent(requests, "PUT")).toEqual(["/captures/c1/chunks/0"]);
  });

  test("counts the retries of one send across its chunks, so a later chunk can fail on its first try", async () => {
    // Arrange
    const unlucky = (request, earlier) => {
      const chunk = request.path.endsWith("/0") ? earlier < 4 : earlier < 1;
      return request.method === "PUT" && chunk
        ? new Response(null, { status: 503 })
        : answer(request);
    };
    const requests = fakeServer(unlucky);
    const recording = await connect();
    speak(recording, 11);
    await vi.advanceTimersByTimeAsync(1);

    // Act
    speak(recording, 10);
    await hangUp(recording);

    // Assert
    expect(sent(requests, "PUT")).toEqual([
      "/captures/c1/chunks/0",
      "/captures/c1/chunks/0",
      "/captures/c1/chunks/0",
      "/captures/c1/chunks/0",
      "/captures/c1/chunks/0",
      "/captures/c1/chunks/1",
    ]);
  });

  test("saves the whole recording as a local file once the upload has failed", async () => {
    // Arrange
    const requests = fakeServer(failingPuts(Number.POSITIVE_INFINITY));
    const recording = await connect();
    speak(recording, 15);

    // Act
    await hangUp(recording);

    // Assert
    expect({
      completed: sent(requests, "POST").includes("/captures/c1/complete"),
      saved: chrome.downloads.download.mock.calls.map(([options]) => options.filename),
      slices: recoveryStore.put.mock.calls[0][0].slices.length,
      blobRequest: chrome.runtime.sendMessage.mock.calls.find(([m]) => m.type === "blob")[0],
    }).toEqual({
      completed: false,
      saved: ["whadio-2026-11-03T10-00-00.webm"],
      slices: 15,
      blobRequest: {
        target: "offscreen",
        type: "blob",
        id: recoveryStore.put.mock.calls[0][0].id,
      },
    });
  });

  test("leaves the capture open and saves nothing when the call ends before any audio", async () => {
    // Arrange
    const requests = fakeServer();
    const recording = await connect();

    // Act
    await hangUp(recording);

    // Assert
    expect({
      requests: requests.map((r) => `${r.method} ${r.path}`),
      saved: chrome.downloads.download.mock.calls.length,
    }).toEqual({ requests: ["POST /captures"], saved: 0 });
  });
});

describe("a server that stops answering", () => {
  test("gives up on a chunk that gets no answer within its deadline and sends it again", async () => {
    // Arrange
    const quiet = (request, earlier, signal) =>
      request.method === "PUT" && earlier === 0
        ? answerAfter(Number.POSITIVE_INFINITY, signal)
        : answer(request);
    const requests = fakeServer(quiet);
    const recording = await connect();

    // Act
    speak(recording, 11);
    await vi.runAllTimersAsync();

    // Assert
    expect(sent(requests, "PUT")).toEqual(["/captures/c1/chunks/0", "/captures/c1/chunks/0"]);
  });

  test("still saves the call locally when no chunk upload ever gets an answer", async () => {
    // Arrange
    const quiet = (request, _earlier, signal) =>
      request.method === "PUT" ? answerAfter(Number.POSITIVE_INFINITY, signal) : answer(request);
    fakeServer(quiet);
    const recording = await connect();
    speak(recording, 15);

    // Act
    await hangUp(recording);

    // Assert
    expect(chrome.downloads.download.mock.calls.map(([options]) => options.filename)).toEqual([
      "whadio-2026-11-03T10-00-00.webm",
    ]);
  });

  test.for([
    [TIMEOUT_MS - 1, 0],
    [TIMEOUT_MS, 1],
  ])(
    "waits for the completion up to the deadline: answered after %i ms, saves %i files",
    async ([delay, saved]) => {
      // Arrange
      const slowComplete = (request, _earlier, signal) =>
        request.path.endsWith("/complete")
          ? answerAfter(delay, signal, json(200, { id: "c1" }))
          : answer(request);
      fakeServer(slowComplete);
      const recording = await connect();
      speak(recording, 15);

      // Act
      await hangUp(recording);

      // Assert
      expect(chrome.downloads.download.mock.calls).toHaveLength(saved);
    },
  );
});
