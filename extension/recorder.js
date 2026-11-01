// Runs in the Meet tab. A recording started from the popup or the shortcut runs in the extension's offscreen
// document; this script then only notes who is speaking. A recording started from the card runs here, where
// the call already holds the microphone permission. It is both a declared content script and injected by the
// popup into tabs opened before the extension was installed; the flag keeps a single copy per page.
if (!globalThis.whadioRecorder) {
  globalThis.whadioRecorder = true;

  let session = null;
  let dismissed = false;

  // --- Recording ---

  // Each tile's level bars move while that participant talks and rest on the quiet class otherwise; the
  // names heard each second go to the background whenever they differ from the second before.
  function listen() {
    const began = performance.now();
    const heard = new Set();
    let previous = "";
    let secondBegan = began;
    let ticks = 0;
    const flush = () => {
      const speakers = [...heard].sort();
      heard.clear();
      // The names belong to when the second began in the audio.
      const at = (secondBegan - began) / 1000;
      secondBegan = performance.now();
      if (speakers.join("\n") !== previous) {
        previous = speakers.join("\n");
        chrome.runtime.sendMessage({ type: "speakers", speakers, at });
      }
    };
    // Meet draws icons as words, such as "devices", in the same notranslate elements as names. Words shaped
    // like an icon name are skipped, and so is a name written that way; the first other span is the name.
    const ICON_LIGATURE = /^[a-z]+(_[a-z]+)*$/;
    const tileName = (tile) => {
      for (const element of tile.querySelectorAll("span.notranslate")) {
        const text = element.textContent.trim();
        if (
          text &&
          !tile.contains(element.closest('[aria-hidden="true"]')) &&
          !ICON_LIGATURE.test(text)
        ) {
          return text;
        }
      }
      return null;
    };
    const interval = setInterval(() => {
      for (const tile of document.querySelectorAll("[data-participant-id]")) {
        const level = tile.querySelector('[jsname="QgSmzd"]');
        const name = tileName(tile);
        if (level && name && !level.classList.contains("gjg47c")) {
          heard.add(name);
        }
      }
      ticks += 1;
      if (ticks % 4 === 0) {
        flush();
      }
    }, 250);
    return { interval, flush };
  }

  function began(startedAt, finish) {
    session = { startedAt, finish, listening: listen() };
    banner.host.remove();
  }

  // The card's picker leaves the tab audible, so unlike a tab capture its audio needs no playing back here.
  async function start(tab) {
    let microphone;
    try {
      // With gain control on, this stream and Meet's would both move the system microphone volume.
      microphone = await navigator.mediaDevices.getUserMedia({ audio: { autoGainControl: false } });
    } catch (failure) {
      for (const track of tab.getTracks()) {
        track.stop();
      }
      throw failure;
    }

    const context = new AudioContext();
    const mix = context.createMediaStreamDestination();
    context.createMediaStreamSource(tab).connect(mix);
    context.createMediaStreamSource(microphone).connect(mix);

    // The audio goes to the background as it is recorded, so closing the tab cannot lose it; the background
    // uploads it as it arrives and completes the recording when this port disconnects, whether the recording
    // stopped or the page went away.
    const port = chrome.runtime.connect({ name: "recording" });
    let sent = Promise.resolve();
    const recorder = new MediaRecorder(mix.stream, { mimeType: "audio/webm;codecs=opus" });
    recorder.addEventListener("dataavailable", (event) => {
      sent = sent.then(async () =>
        port.postMessage({ audio: base64(await event.data.arrayBuffer()) }),
      );
    });
    recorder.addEventListener("stop", () => sent.then(() => port.disconnect()), { once: true });
    recorder.start(1000);

    const finish = () => {
      recorder.stop();
      for (const stream of [tab, microphone]) {
        for (const track of stream.getTracks()) {
          track.stop();
        }
      }
      void context.close();
    };
    began(Date.now(), finish);
    tab.getAudioTracks()[0].addEventListener("ended", () => {
      if (session?.finish === finish) {
        stop();
      }
    });
  }

  function base64(buffer) {
    const bytes = new Uint8Array(buffer);
    let binary = "";
    for (let offset = 0; offset < bytes.length; offset += 0x8000) {
      binary += String.fromCharCode(...bytes.subarray(offset, offset + 0x8000));
    }
    return btoa(binary);
  }

  async function captureWithPicker() {
    const stream = await navigator.mediaDevices.getDisplayMedia({
      video: true,
      audio: { suppressLocalAudioPlayback: false },
      preferCurrentTab: true,
      selfBrowserSurface: "include",
    });
    for (const track of stream.getVideoTracks()) {
      track.stop();
    }
    if (stream.getAudioTracks().length === 0) {
      throw new Error('Keep "Also share tab audio" switched on, or the call is not recorded.');
    }
    return stream;
  }

  // A recording that already ended elsewhere, such as in the offscreen document, needs no finishing.
  function stop(ended = false) {
    const { finish, listening } = session;
    session = null;
    clearInterval(listening.interval);
    // Recorded once already, so the card stays away for the rest of this call.
    dismissed = true;
    if (!ended) {
      listening.flush();
      finish();
    }
  }

  // --- Banner offering to record, or to sign in first ---

  // Built with DOM calls rather than innerHTML, which Meet's Trusted Types policy refuses.
  function element(tag, properties, children = []) {
    const node = Object.assign(document.createElement(tag), properties);
    node.append(...children);
    return node;
  }

  function buildBanner() {
    const host = element("div");
    const root = host.attachShadow({ mode: "closed" });
    const consent = element("input", { type: "checkbox" });
    const startButton = element("button", {
      textContent: "Start recording",
      className: "primary",
      disabled: true,
    });
    const later = element("button", { textContent: "Not now" });
    const error = element("p", { className: "error", hidden: true });
    const close = element("button", { textContent: "Close" });
    const neverAgain = element("button", { textContent: "Don't show again" });
    // Passwords are typed only into the extension's own popup: scripts on Meet's page see every key pressed here.
    const signInPanel = element("div", {}, [
      element("h2", { textContent: "Sign in to Whadio" }),
      element("p", {
        textContent: "To record this call, sign in from the Whadio button in the Chrome toolbar.",
      }),
      element("div", { className: "actions" }, [close, neverAgain]),
    ]);
    const recordPanel = element("div", {}, [
      element("h2", { textContent: "Record this call with Whadio?" }),
      element("p", {
        textContent: "Tell everyone you are recording, and record only once they agree.",
      }),
      element("label", {}, [consent, "Everyone in the call agreed to be recorded"]),
      element("div", { className: "actions" }, [startButton, later]),
      element("p", { className: "hint", textContent: "Or tick the box and press Alt+Shift+R." }),
    ]);
    let signedIn = false;
    let promptSignIn = true;

    root.append(
      element("style", {
        textContent: `
          .card { position: fixed; top: 16px; right: 16px; z-index: 2147483647; width: 300px; padding: 16px;
            border-radius: 12px; background: #fff; color: #202124; box-shadow: 0 4px 16px rgb(0 0 0 / 30%);
            font: 14px/1.4 system-ui, sans-serif; }
          h2 { margin: 0 0 8px; font-size: 16px; }
          p { margin: 0 0 8px; }
          label { display: flex; gap: 8px; align-items: flex-start; margin: 8px 0 12px; }
          .actions { display: flex; gap: 8px; }
          button { flex: 1; padding: 8px; border: 1px solid #dadce0; border-radius: 6px; background: #fff;
            font: inherit; cursor: pointer; }
          button.primary { border-color: #1a73e8; background: #1a73e8; color: #fff; }
          button:disabled { opacity: 0.5; cursor: default; }
          .hint { margin: 8px 0 0; color: #5f6368; font-size: 12px; }
          .error { margin: 8px 0 0; color: #d93025; }
        `,
      }),
      element("div", { className: "card" }, [signInPanel, recordPanel, error]),
    );

    // Recording is offered only once signed in. The token lives where this page cannot read it, so the
    // background answers whether there is one.
    async function refresh() {
      const { signInPrompt } = await chrome.storage.local.get("signInPrompt");
      signedIn = await chrome.runtime.sendMessage({ type: "signed-in" });
      promptSignIn = signInPrompt !== false;
      signInPanel.hidden = signedIn;
      recordPanel.hidden = !signedIn;
      error.hidden = true;
    }
    chrome.storage.onChanged.addListener(async (changes, area) => {
      if (area === "local" && ("signInPrompt" in changes || "signInChangedAt" in changes)) {
        await refresh();
        if (!signedIn && !promptSignIn) {
          host.remove();
        }
      }
    });

    // Meet handles keys on the whole page; Space on the checkbox or a button must not reach its push-to-talk.
    root.addEventListener("keydown", (event) => event.stopPropagation());
    for (const button of [close, later]) {
      button.addEventListener("click", () => {
        dismissed = true;
        host.remove();
      });
    }
    neverAgain.addEventListener("click", async () => {
      await chrome.storage.local.set({ signInPrompt: false });
      host.remove();
    });
    consent.addEventListener("change", () => {
      startButton.disabled = !consent.checked;
    });
    startButton.addEventListener("click", async () => {
      startButton.disabled = true;
      // The sign-in may have ended since the card appeared.
      await refresh();
      if (!signedIn) {
        return;
      }
      try {
        await start(await captureWithPicker());
      } catch (failure) {
        showError(failure.message);
        startButton.disabled = false;
      }
    });

    function showError(message) {
      error.textContent = message;
      error.hidden = false;
    }

    return {
      host,
      consent,
      showError,
      refresh,
      wanted: () => signedIn || promptSignIn,
      signedIn: () => signedIn,
    };
  }

  const banner = buildBanner();

  function inCall() {
    return [...document.querySelectorAll("button")].some((button) =>
      button.textContent.includes("call_end"),
    );
  }

  setInterval(async () => {
    if (!inCall()) {
      dismissed = false;
      banner.host.remove();
    } else if (!session && !dismissed && !banner.host.isConnected && banner.wanted()) {
      // A token can expire while the card is away, so it checks again each time it would appear.
      await banner.refresh();
      if (banner.wanted() && !session && !dismissed) {
        document.body.append(banner.host);
      }
    }
  }, 1000);

  // --- Leaving the call ---

  // Meet's hang-up button is found by its icon name, which unlike its label does not change with the interface language.
  document.addEventListener(
    "click",
    (event) => {
      if (session && event.target.closest("button")?.textContent.includes("call_end")) {
        stop();
      }
    },
    true,
  );
  window.addEventListener("beforeunload", (event) => {
    if (session) {
      event.preventDefault();
    }
  });

  // --- Messages from the popup and the keyboard shortcut ---

  chrome.runtime.onMessage.addListener((message, _sender, sendResponse) => {
    if (message.type === "status") {
      sendResponse({ consented: banner.consent.checked });
      return;
    }
    if (message.type === "hide-card") {
      // The toolbar popup took over, so the card stays away for the rest of this call.
      dismissed = true;
      banner.host.remove();
      return;
    }
    if (message.type === "ask-sign-in") {
      // Asked for with the shortcut, so the sign-in card shows even after "Don't show again".
      dismissed = false;
      banner.refresh().then(() => document.body.append(banner.host));
      return;
    }
    if (message.type === "ask-consent") {
      dismissed = false;
      banner
        .refresh()
        .then(() => {
          document.body.append(banner.host);
          banner.showError("Tick the box first, then press Alt+Shift+R again.");
        })
        // Fails only once the extension is reloaded under this page, when nothing here can reach it.
        .catch(() => {});
      return;
    }
    if (message.type === "show-error") {
      dismissed = false;
      document.body.append(banner.host);
      banner.showError(message.error);
      return;
    }
    // The offscreen document records; the background reports when it started and when it ended.
    if (message.type === "started") {
      began(message.startedAt, () => chrome.runtime.sendMessage({ type: "stop-recording" }));
      // Held for as long as this page lives: its disconnect on a reload or a navigation ends the recording.
      chrome.runtime.connect({ name: "page" });
      return;
    }
    if (message.type === "flush-speakers") {
      session?.listening.flush();
      return;
    }
    if (message.type === "stopped") {
      if (session) {
        stop(true);
      }
      return;
    }
    if (message.type === "stop") {
      if (session) {
        stop();
      }
      sendResponse({});
    }
  });
}
