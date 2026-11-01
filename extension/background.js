import { api, signedIn } from "./server.js";

// MediaRecorder hands over one slice a second; ten of them make one uploaded chunk.
const SLICES_PER_CHUNK = 10;
const RETRIES = 5;

function downloaded(downloadId) {
  return new Promise((resolve) => {
    function listener(delta) {
      if (delta.id === downloadId && delta.state && delta.state.current !== "in_progress") {
        chrome.downloads.onChanged.removeListener(listener);
        resolve();
      }
    }
    chrome.downloads.onChanged.addListener(listener);
  });
}

async function saveLocally(startedAt, slices) {
  if (slices.length === 0) {
    return;
  }
  // A service worker cannot make a blob URL, so an offscreen document turns the audio into one.
  if (!(await chrome.offscreen.hasDocument())) {
    await chrome.offscreen.createDocument({
      url: "offscreen.html",
      reasons: ["BLOBS"],
      justification: "Turns a recording the server did not take into a file to download.",
    });
  }
  const { url } = await chrome.runtime.sendMessage({ target: "offscreen", chunks: slices });
  const stamp = new Date(startedAt).toISOString().slice(0, 19).replaceAll(":", "-");
  const downloadId = await chrome.downloads.download({ url, filename: `whadio-${stamp}.webm` });
  await downloaded(downloadId);
  await chrome.offscreen.closeDocument();
}

function bytes(slices) {
  const parts = slices.map((slice) => Uint8Array.from(atob(slice), (char) => char.charCodeAt(0)));
  return new Blob(parts, { type: "audio/webm" });
}

function pause(attempt) {
  return new Promise((resolve) => setTimeout(resolve, 1000 * 2 ** attempt));
}

// One recording: opens a capture, uploads its chunks in order as they fill, resumes from what the
// server already holds after a failure, and completes it once the tab stops sending audio.
class Upload {
  constructor(startedAt, destination) {
    this.startedAt = startedAt;
    this.destination = destination;
    this.slices = [];
    this.chunks = [];
    this.events = [];
    this.capture = null;
    this.uploaded = new Set();
    this.queue = Promise.resolve();
    this.failed = false;
  }

  add(message) {
    this.slices.push(message.audio);
    if (message.speakers) {
      this.events.push({ at_seconds: message.at, speakers: message.speakers });
    }
    if (this.slices.length % SLICES_PER_CHUNK === 0) {
      this.cut();
    }
  }

  cut() {
    const from = this.chunks.reduce((total, chunk) => total + chunk.slices, 0);
    if (from === this.slices.length) {
      return;
    }
    this.chunks.push({
      slices: this.slices.length - from,
      audio: bytes(this.slices.slice(from)),
      events: this.events,
    });
    this.events = [];
    this.queue = this.queue.then(() => this.send());
  }

  async open() {
    if (this.capture) {
      return;
    }
    this.capture = await api("POST", "/captures", { ...this.destination, consent_confirmed: true });
  }

  async send() {
    for (let attempt = 0; !this.failed; attempt += 1) {
      try {
        await this.open();
        for (const [seq, chunk] of this.chunks.entries()) {
          if (!this.uploaded.has(seq)) {
            const form = new FormData();
            form.append("audio", chunk.audio, `${seq}.webm`);
            form.append("speaker_events", JSON.stringify(chunk.events));
            await api("PUT", `/captures/${this.capture.id}/chunks/${seq}`, form);
            this.uploaded.add(seq);
          }
        }
        return;
      } catch (failure) {
        if (attempt + 1 >= RETRIES || failure.status === 401 || failure.status === 404) {
          this.failed = true;
          return;
        }
        await pause(attempt);
        if (this.capture) {
          // A response lost on the way may have stored a chunk; the server tells which it holds.
          const found = await api("GET", `/captures/${this.capture.id}`).catch(() => null);
          for (const seq of found?.received_seqs ?? []) {
            this.uploaded.add(seq);
          }
        }
      }
    }
  }

  async finish() {
    this.cut();
    await this.queue;
    if (!this.failed && this.chunks.length > 0) {
      try {
        await api("POST", `/captures/${this.capture.id}/complete`, {
          last_seq: this.chunks.length - 1,
        });
        return;
      } catch {
        // Saved below instead, so the call is not lost.
      }
    }
    await saveLocally(this.startedAt, this.slices);
  }
}

chrome.runtime.onConnect.addListener(async (port) => {
  if (port.name !== "recording" || !port.sender?.tab) {
    return;
  }
  const tabId = port.sender.tab.id;
  const { destination } = await chrome.storage.local.get("destination");
  const upload = new Upload(Date.now(), destination ?? {});
  // Opened at once rather than with the first chunk, so the meeting's time is when recording began.
  upload.queue = upload.queue.then(() => upload.send());
  port.onMessage.addListener((message) => upload.add(message));
  port.onDisconnect.addListener(async () => {
    // The tab may already be closed, so clearing its badge may fail.
    chrome.action.setBadgeText({ tabId, text: "" }).catch(() => {});
    await upload.finish();
  });

  await chrome.action.setBadgeText({ tabId, text: "REC" });
});

// Installs signed in before the token moved to session storage still hold it where content scripts can read it.
chrome.runtime.onInstalled.addListener(() =>
  chrome.storage.local.remove(["token", "expiresAt", "name"]),
);

// Session storage sends the Meet page no change events, so a sign-in or sign-out reaches the card as a
// timestamp in local storage, which carries nothing secret.
chrome.storage.session.onChanged.addListener((changes) => {
  if ("token" in changes) {
    chrome.storage.local.set({ signInChangedAt: Date.now() });
  }
});

// The card on the Meet page cannot read the token, so it asks here whether the user is signed in.
chrome.runtime.onMessage.addListener((message, _sender, sendResponse) => {
  if (message.type !== "signed-in") {
    return false;
  }
  signedIn().then(sendResponse, () => sendResponse(false));
  return true;
});

// The shortcut counts as invoking the extension on the tab, which Chrome requires before it hands out a tab capture.
chrome.commands.onCommand.addListener(async (command, tab) => {
  if (command !== "toggle-recording" || !tab?.url?.startsWith("https://meet.google.com/")) {
    return;
  }
  await chrome.scripting.executeScript({ target: { tabId: tab.id }, files: ["recorder.js"] });
  const status = await chrome.tabs.sendMessage(tab.id, { type: "status" });
  if (status.startedAt) {
    await chrome.tabs.sendMessage(tab.id, { type: "stop" });
  } else if (!(await signedIn())) {
    await chrome.tabs.sendMessage(tab.id, { type: "ask-sign-in" });
  } else if (!status.consented) {
    await chrome.tabs.sendMessage(tab.id, { type: "ask-consent" });
  } else {
    const streamId = await chrome.tabCapture.getMediaStreamId({
      targetTabId: tab.id,
      consumerTabId: tab.id,
    });
    await chrome.tabs.sendMessage(tab.id, { type: "start", streamId });
  }
});
