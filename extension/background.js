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

// The offscreen document records the calls and stays open, since closing it would end every recording.
async function offscreen() {
  if (!(await chrome.offscreen.hasDocument())) {
    await chrome.offscreen.createDocument({
      url: "offscreen.html",
      reasons: ["USER_MEDIA", "BLOBS"],
      justification: "Records the Meet call and turns a recording the server did not take into a file to download.",
    });
  }
}

// Recordings being started or saved, which keep the offscreen document open while no upload is under way.
let pending = 0;

async function closeOffscreenIfIdle() {
  if (pending === 0 && uploads.size === 0 && (await chrome.offscreen.hasDocument())) {
    await chrome.offscreen.closeDocument();
  }
}

async function saveLocally(startedAt, slices) {
  if (slices.length === 0) {
    return;
  }
  pending += 1;
  try {
    await offscreen();
    const { url } = await chrome.runtime.sendMessage({ target: "offscreen", type: "blob", chunks: slices });
    const stamp = new Date(startedAt).toISOString().slice(0, 19).replaceAll(":", "-");
    const downloadId = await chrome.downloads.download({ url, filename: `whadio-${stamp}.webm` });
    await downloaded(downloadId);
    await chrome.runtime.sendMessage({ target: "offscreen", type: "revoke", url });
  } finally {
    pending -= 1;
  }
}

async function record(tabId, streamId) {
  pending += 1;
  try {
    await offscreen();
    const reply = await chrome.runtime.sendMessage({ target: "offscreen", type: "record", tabId, streamId });
    if (reply.microphone) {
      await chrome.tabs.create({ url: "permission.html" });
    }
    if (!reply.error) {
      try {
        await chrome.tabs.sendMessage(tabId, { type: "started", startedAt: reply.startedAt });
      } catch (failure) {
        // The page went away while the streams opened; nothing there could stop this recording.
        await chrome.runtime.sendMessage({ target: "offscreen", type: "stop", tabId });
        throw failure;
      }
    }
    return reply;
  } finally {
    pending -= 1;
  }
}

// The page's last speaker names go out before the audio ends, so the final stretch keeps its speaker.
async function stopRecording(tabId) {
  const upload = uploads.get(tabId);
  if (!upload) {
    return;
  }
  if (upload.offscreen) {
    await chrome.tabs.sendMessage(tabId, { type: "flush-speakers" }).catch(() => {});
    await chrome.runtime.sendMessage({ target: "offscreen", type: "stop", tabId });
  } else {
    await chrome.tabs.sendMessage(tabId, { type: "stop" });
  }
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
  constructor(startedAt, offscreen) {
    this.startedAt = startedAt;
    this.offscreen = offscreen;
    this.slices = [];
    this.sliced = 0;
    this.chunks = [];
    this.events = [];
    this.capture = null;
    this.uploaded = new Set();
    this.queue = Promise.resolve();
    this.failed = false;
  }

  add(audio) {
    this.slices.push(audio);
    // One slice stays back, so the final chunk always has audio to carry the last speaker events.
    if (this.slices.length - this.sliced > SLICES_PER_CHUNK) {
      this.cut(this.sliced + SLICES_PER_CHUNK);
    }
  }

  hear(at, speakers) {
    this.events.push({ at_seconds: at, speakers });
  }

  cut(to = this.slices.length) {
    if (to === this.sliced) {
      return;
    }
    this.chunks.push({ audio: bytes(this.slices.slice(this.sliced, to)), events: this.events });
    this.sliced = to;
    this.events = [];
    this.queue = this.queue.then(() => this.send());
  }

  async open() {
    if (this.capture) {
      return;
    }
    const { destination } = await chrome.storage.local.get("destination");
    this.capture = await api("POST", "/captures", { ...destination, consent_confirmed: true });
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

// The recording under way in each tab, which the tab's speaker names join.
const uploads = new Map();

// A card recording connects from its tab as "recording"; one from the offscreen document names its tab.
function recordedTab(port) {
  if (port.sender?.tab) {
    return port.name === "recording" ? port.sender.tab.id : null;
  }
  const match = /^recording:(\d+)$/.exec(port.name);
  return match ? Number(match[1]) : null;
}

chrome.runtime.onConnect.addListener(async (port) => {
  // A Meet page holds this port while the offscreen document records it. Tab capture outlives a reload
  // or a navigation, so the page going away is what ends that recording.
  if (port.name === "page" && port.sender?.tab) {
    const tabId = port.sender.tab.id;
    port.onDisconnect.addListener(() => {
      if (uploads.get(tabId)?.offscreen) {
        chrome.runtime.sendMessage({ target: "offscreen", type: "stop", tabId }).catch(() => {});
      }
    });
    return;
  }
  const tabId = recordedTab(port);
  if (tabId === null) {
    return;
  }
  const upload = new Upload(Date.now(), !port.sender?.tab);
  uploads.set(tabId, upload);
  // Opened at once rather than with the first chunk, so the meeting's time is when recording began.
  upload.queue = upload.queue.then(() => upload.send());
  port.onMessage.addListener((message) => upload.add(message.audio));
  port.onDisconnect.addListener(async () => {
    uploads.delete(tabId);
    // The tab may already be closed, so telling it and clearing its badge may fail.
    chrome.tabs.sendMessage(tabId, { type: "stopped" }).catch(() => {});
    chrome.action.setBadgeText({ tabId, text: "" }).catch(() => {});
    await upload.finish();
    await closeOffscreenIfIdle();
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

chrome.runtime.onMessage.addListener((message, sender, sendResponse) => {
  if (message.type === "speakers") {
    uploads.get(sender.tab?.id)?.hear(message.at, message.speakers);
    return false;
  }
  // The recordings live here and in the offscreen document, so the popup asks here rather than the page,
  // which forgets them on a reload.
  if (message.type === "recording") {
    sendResponse({ startedAt: uploads.get(message.tabId)?.startedAt ?? null });
    return false;
  }
  if (message.type === "stop-recording") {
    stopRecording(message.tabId ?? sender.tab?.id).then(
      () => sendResponse({}),
      () => sendResponse({}),
    );
    return true;
  }
  if (message.type === "record") {
    record(message.tabId, message.streamId).then(sendResponse, (failure) => sendResponse({ error: failure.message }));
    return true;
  }
  return false;
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
  if (uploads.has(tab.id)) {
    await stopRecording(tab.id);
    return;
  }
  try {
    await chrome.scripting.executeScript({ target: { tabId: tab.id }, files: ["recorder.js"] });
    const status = await chrome.tabs.sendMessage(tab.id, { type: "status" });
    if (!(await signedIn())) {
      await chrome.tabs.sendMessage(tab.id, { type: "ask-sign-in" });
    } else if (!status.consented) {
      await chrome.tabs.sendMessage(tab.id, { type: "ask-consent" });
    } else {
      const streamId = await chrome.tabCapture.getMediaStreamId({ targetTabId: tab.id });
      const reply = await record(tab.id, streamId);
      if (reply.error) {
        throw new Error(reply.error);
      }
    }
  } catch (failure) {
    // The page may be gone too, so the error may have nowhere to show.
    await chrome.tabs.sendMessage(tab.id, { type: "show-error", error: failure.message }).catch(() => {});
  }
});
