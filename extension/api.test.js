import { api, signIn, TIMEOUT_MS } from "./api.js";

const SERVER = "https://whadio.example";

function fakeChrome() {
  return {
    storage: {
      session: {
        get: async () => ({ server: SERVER, token: "t" }),
        set: vi.fn(async () => {}),
        remove: async () => {},
      },
      local: { set: vi.fn(async () => {}), remove: async () => {} },
    },
  };
}

// Never answers, as over a connection that went quiet; only the request's signal ends it.
function noAnswer(_url, init) {
  return new Promise((_resolve, reject) => {
    init.signal?.addEventListener("abort", () => reject(init.signal.reason));
  });
}

// Sends the headers and part of the body, then stalls. Like Chromium, the body read is cut off with an
// AbortError once the signal aborts, whatever the signal's reason.
async function partialBody(_url, init) {
  const body = new ReadableStream({
    start(controller) {
      controller.enqueue(new TextEncoder().encode('{"token":'));
      init.signal?.addEventListener("abort", () =>
        controller.error(new DOMException("BodyStreamBuffer was aborted", "AbortError")),
      );
    },
  });
  return new Response(body, { status: 200, headers: { "Content-Type": "application/json" } });
}

// Lets `elapsed` pass on the fake clock and reports how the request ended.
async function outcomeAfter(request, elapsed) {
  const outcome = request.then(
    () => "answered",
    (error) => error,
  );
  await vi.advanceTimersByTimeAsync(elapsed);
  return outcome;
}

beforeEach(() => {
  vi.useFakeTimers();
  globalThis.chrome = fakeChrome();
});

afterEach(() => {
  vi.useRealTimers();
});

describe("signing in to a server that stops answering", () => {
  test("gives up once no answer has arrived by the deadline", async () => {
    // Arrange
    globalThis.fetch = vi.fn(noAnswer);

    // Act
    const outcome = await outcomeAfter(signIn(SERVER, "a@example.com", "secret"), TIMEOUT_MS);

    // Assert
    expect(outcome).toHaveProperty("name", "TimeoutError");
  });

  test("stores no session when it gives up", async () => {
    // Arrange
    globalThis.fetch = vi.fn(noAnswer);

    // Act
    await outcomeAfter(signIn(SERVER, "a@example.com", "secret"), TIMEOUT_MS);

    // Assert
    expect(chrome.storage.session.set).not.toHaveBeenCalled();
  });

  test("gives up on an answer that stops partway as a timeout", async () => {
    // Arrange
    globalThis.fetch = vi.fn(partialBody);

    // Act
    const outcome = await outcomeAfter(signIn(SERVER, "a@example.com", "secret"), TIMEOUT_MS);

    // Assert
    expect(outcome).toHaveProperty("name", "TimeoutError");
  });
});

describe("a request whose answer stops partway", () => {
  test("gives up as a timeout once the deadline passes", async () => {
    // Arrange
    globalThis.fetch = vi.fn(partialBody);

    // Act
    const outcome = await outcomeAfter(api("GET", "/captures/c1"), TIMEOUT_MS);

    // Assert
    expect(outcome).toHaveProperty("name", "TimeoutError");
  });
});
