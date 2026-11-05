// @vitest-environment jsdom

let root;

function event() {
  const listeners = [];
  return { listeners, addListener: (listener) => listeners.push(listener) };
}

function fakeChrome({ signedIn = true, unreachable = false } = {}) {
  return {
    runtime: {
      onMessage: event(),
      connect: vi.fn(),
      sendMessage: vi.fn(async (message) => {
        if (message.type !== "signed-in") {
          return undefined;
        }
        if (unreachable) {
          throw new Error("Extension context invalidated.");
        }
        return signedIn;
      }),
    },
    storage: {
      local: { get: async () => ({}), set: async () => {} },
      onChanged: event(),
    },
  };
}

async function load(options) {
  globalThis.chrome = fakeChrome(options);
  await import("./recorder.js");
}

function send(message) {
  const sendResponse = vi.fn();
  chrome.runtime.onMessage.listeners[0](message, {}, sendResponse);
  return sendResponse;
}

function cardShown() {
  return root.host.isConnected;
}

function cardError() {
  const error = root.querySelector(".error");
  return error.hidden ? null : error.textContent;
}

function panelShown() {
  return [...root.querySelectorAll("h2")].find((title) => !title.parentElement.hidden)?.textContent;
}

function sentTypes() {
  return chrome.runtime.sendMessage.mock.calls.map(([message]) => message.type);
}

function joinCall() {
  document.body.append(
    Object.assign(document.createElement("button"), { textContent: "call_end" }),
  );
}

function speaking(name) {
  const tile = document.createElement("div");
  tile.dataset.participantId = name;
  const label = Object.assign(document.createElement("span"), { className: "notranslate" });
  label.textContent = name;
  const level = document.createElement("div");
  level.setAttribute("jsname", "QgSmzd");
  tile.append(label, level);
  document.body.append(tile);
}

function speakersSent() {
  return chrome.runtime.sendMessage.mock.calls
    .map(([message]) => message)
    .filter((message) => message.type === "speakers")
    .map((message) => message.speakers);
}

beforeEach(() => {
  vi.useFakeTimers();
  vi.resetModules();
  document.body.replaceChildren();
  delete globalThis.whadioRecorder;
  const attachShadow = Element.prototype.attachShadow;
  vi.spyOn(Element.prototype, "attachShadow").mockImplementation(function (init) {
    root = attachShadow.call(this, init);
    return root;
  });
});

afterEach(() => {
  vi.clearAllTimers();
  vi.useRealTimers();
  vi.restoreAllMocks();
});

describe("the recorder's answers to the extension", () => {
  test("reports no consent before the box is ticked", async () => {
    // Arrange
    await load();

    // Act
    const sendResponse = send({ type: "status" });

    // Assert
    expect(sendResponse).toHaveBeenCalledWith({ consented: false });
  });

  test("reports consent once the box is ticked", async () => {
    // Arrange
    await load();
    root.querySelector('input[type="checkbox"]').checked = true;

    // Act
    const sendResponse = send({ type: "status" });

    // Assert
    expect(sendResponse).toHaveBeenCalledWith({ consented: true });
  });

  test("hides the card and keeps it away for the rest of the call", async () => {
    // Arrange
    await load();
    joinCall();
    await vi.advanceTimersByTimeAsync(1000);

    // Act
    send({ type: "hide-card" });
    await vi.advanceTimersByTimeAsync(3000);

    // Assert
    expect(cardShown()).toBe(false);
  });

  test("shows the sign-in card when asked to, even after it was dismissed", async () => {
    // Arrange
    await load({ signedIn: false });
    send({ type: "hide-card" });

    // Act
    send({ type: "ask-sign-in" });
    await vi.advanceTimersByTimeAsync(0);

    // Assert
    expect([cardShown(), panelShown()]).toEqual([true, "Sign in to Whadio"]);
  });

  test("shows the card with a hint to tick the box when consent is missing", async () => {
    // Arrange
    await load();

    // Act
    send({ type: "ask-consent" });
    await vi.advanceTimersByTimeAsync(0);

    // Assert
    expect([cardShown(), cardError()]).toEqual([
      true,
      "Tick the box first, then press Alt+Shift+R again.",
    ]);
  });

  test("shows nothing when the extension is unreachable as consent is asked for", async () => {
    // Arrange
    await load({ unreachable: true });

    // Act
    send({ type: "ask-consent" });
    await vi.advanceTimersByTimeAsync(0);

    // Assert
    expect(cardShown()).toBe(false);
  });

  test("shows nothing when the extension is unreachable as sign-in is asked for", async () => {
    // Arrange
    await load({ unreachable: true });

    // Act
    send({ type: "ask-sign-in" });
    await vi.advanceTimersByTimeAsync(0);

    // Assert
    expect(cardShown()).toBe(false);
  });

  test("shows an error on the card without asking whether the user is signed in", async () => {
    // Arrange
    await load();

    // Act
    send({ type: "show-error", error: "The server is unreachable." });

    // Assert
    expect([cardShown(), cardError(), sentTypes()]).toEqual([
      true,
      "The server is unreachable.",
      [],
    ]);
  });

  test("holds a page port while a recording runs in the offscreen document", async () => {
    // Arrange
    await load();

    // Act
    send({ type: "started", startedAt: 0 });

    // Assert
    expect(chrome.runtime.connect).toHaveBeenCalledWith({ name: "page" });
  });

  test("sends the speakers of the second when asked to flush them", async () => {
    // Arrange
    await load();
    speaking("Zoe");
    send({ type: "started", startedAt: 0 });
    await vi.advanceTimersByTimeAsync(250);

    // Act
    send({ type: "flush-speakers" });

    // Assert
    expect(speakersSent()).toEqual([["Zoe"]]);
  });

  test("sends the speakers of each second sorted by their code units", async () => {
    // Arrange
    await load();
    for (const name of ["Олена", "anna", "Zoe", "Émile"]) {
      speaking(name);
    }
    send({ type: "started", startedAt: 0 });

    // Act
    await vi.advanceTimersByTimeAsync(1000);

    // Assert
    expect(speakersSent()).toEqual([["Zoe", "anna", "Émile", "Олена"]]);
  });

  test("ends a recording that stopped elsewhere without asking to stop it", async () => {
    // Arrange
    await load();
    send({ type: "started", startedAt: 0 });

    // Act
    send({ type: "stopped" });
    send({ type: "stop" });

    // Assert
    expect(sentTypes()).toEqual([]);
  });

  test("asks the background to stop the recording and answers when told to stop", async () => {
    // Arrange
    await load();
    send({ type: "started", startedAt: 0 });

    // Act
    const sendResponse = send({ type: "stop" });

    // Assert
    expect([sentTypes(), sendResponse.mock.calls]).toEqual([["stop-recording"], [[{}]]]);
  });

  test("answers a stop without a recording and stops nothing", async () => {
    // Arrange
    await load();

    // Act
    const sendResponse = send({ type: "stop" });

    // Assert
    expect([sentTypes(), sendResponse.mock.calls]).toEqual([[], [[{}]]]);
  });

  test("ignores a message it does not know", async () => {
    // Arrange
    await load();

    // Act
    const sendResponse = send({ type: "toString" });

    // Assert
    expect([sentTypes(), sendResponse.mock.calls, cardShown()]).toEqual([[], [], false]);
  });
});
