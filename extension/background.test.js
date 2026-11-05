import { COMPLETE_TIMEOUT_MS } from "./api.js";

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
      onConnect: event(),
      onInstalled: event(),
      onMessage: event(),
      sendMessage: vi.fn(async (message) => (message.type === "blob" ? { url: "blob:call" } : {})),
    },
    storage: {
      session: {
        get: async () => ({ server: SERVER, token: "t", expiresAt: "2026-11-04T10:00:00Z" }),
        set: async () => {},
        remove: async () => {},
        onChanged: event(),
      },
      local: { get: async () => ({ destination: DESTINATION }), set: async () => {} },
    },
    tabs: { sendMessage: async () => {} },
    action: { setBadgeText: async () => {} },
    commands: { onCommand: event() },
    offscreen: { hasDocument: async () => false, createDocument: async () => {} },
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

function port() {
  return { name: "recording:7", onMessage: event(), onDisconnect: event() };
}

async function connect() {
  const recording = port();
  await chrome.runtime.onConnect.listeners[0](recording);
  return recording;
}

function speak(recording, slices) {
  for (let slice = 0; slice < slices; slice += 1) {
    recording.onMessage.listeners[0]({ audio: btoa("ab") });
  }
}

function hear(at, speakers) {
  chrome.runtime.onMessage.listeners[0]({ type: "speakers", at, speakers }, { tab: { id: 7 } });
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
  globalThis.chrome = fakeChrome();
  await import("./background.js");
});

afterEach(() => {
  vi.useRealTimers();
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
      slices: chrome.runtime.sendMessage.mock.calls.find(([m]) => m.type === "blob")[0].chunks
        .length,
    }).toEqual({ completed: false, saved: ["whadio-2026-11-03T10-00-00.webm"], slices: 15 });
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
    [COMPLETE_TIMEOUT_MS - 1, 0],
    [COMPLETE_TIMEOUT_MS, 1],
  ])(
    "waits up to the completion deadline: answered after %i ms, saves %i files",
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
