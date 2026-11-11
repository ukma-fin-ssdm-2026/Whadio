import { api, sessionOwner, signedIn, signIn, signOut, TIMEOUT_MS } from "./api.js";

const SERVER = "https://whadio.example";

function fakeChrome() {
  return {
    storage: {
      session: {
        get: async () => ({ server: SERVER, token: "t" }),
        set: vi.fn(async () => {}),
        remove: vi.fn(async () => {}),
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

describe("the original account used for recording recovery", () => {
  test("keeps the server-returned user ID only in session storage", async () => {
    // Arrange
    globalThis.fetch = vi.fn(async () =>
      Response.json({
        token: "new-token",
        expires_at: "2030-01-01T00:00:00Z",
        user: { id: "original", name: "Alice" },
      }),
    );

    // Act
    await signIn(SERVER, "alice@example.com", "secret");

    // Assert
    expect({
      session: chrome.storage.session.set.mock.calls[0][0],
      local: chrome.storage.local.set.mock.calls[0][0],
    }).toEqual({
      session: {
        server: SERVER,
        userId: "original",
        token: "new-token",
        expiresAt: "2030-01-01T00:00:00Z",
        name: "Alice",
      },
      local: { server: SERVER },
    });
  });

  test.for([-1, 0, 1])(
    "a sign-in is valid only before its expiry, offset %i ms",
    async (offset) => {
      // Arrange
      const now = Date.now();
      chrome.storage.session.get = async () => ({
        server: SERVER,
        userId: "original",
        token: "t",
        expiresAt: new Date(now + offset).toISOString(),
      });

      // Act
      const result = await sessionOwner();

      // Assert
      expect(result).toEqual(offset > 0 ? { server: SERVER, userId: "original" } : null);
    },
  );

  test("an old session without its verified account ID requires signing in again", async () => {
    // Arrange
    chrome.storage.session.get = async () => ({
      server: SERVER,
      token: "t",
      expiresAt: "2030-01-01T00:00:00Z",
    });

    // Act
    const result = await signedIn();

    // Assert
    expect(result).toBe(false);
  });

  test("signing out removes the cached recovery identity", async () => {
    // Arrange
    globalThis.fetch = vi.fn(async () => new Response(null, { status: 204 }));

    // Act
    await signOut();

    // Assert
    expect(chrome.storage.session.remove).toHaveBeenCalledWith([
      "token",
      "expiresAt",
      "name",
      "userId",
    ]);
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
