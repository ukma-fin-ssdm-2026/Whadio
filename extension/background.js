import { api, sessionOwner, signedIn } from "./api.js";
import { downloadFile } from "./downloads.js";
import { RecordingRecovery } from "./recovery.js";
import { recoveryStore } from "./recovery-store.js";

// MediaRecorder hands over one slice a second; ten of them make one uploaded chunk.
const SLICES_PER_CHUNK = 10;
const RETRIES = 5;

// The offscreen document records the calls; it is closed once nothing is recording, starting or saving.
async function offscreen() {
  if (!(await chrome.offscreen.hasDocument())) {
    await chrome.offscreen.createDocument({
      url: "offscreen.html",
      reasons: ["USER_MEDIA", "BLOBS"],
      justification:
        "Records the Meet call and turns a recording the server did not take into a file to download.",
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
  let url;
  try {
    await offscreen();
    ({ url } = await chrome.runtime.sendMessage({
      target: "offscreen",
      type: "blob",
      chunks: slices,
    }));
    if (typeof url !== "string" || !url.startsWith("blob:")) {
      throw new Error("The recording file could not be prepared.");
    }
    const stamp = new Date(startedAt).toISOString().slice(0, 19).replaceAll(":", "-");
    await downloadFile({ url, filename: `whadio-${stamp}.webm` });
  } finally {
    if (url) {
      await chrome.runtime.sendMessage({ target: "offscreen", type: "revoke", url }).catch(() => {
        console.warn("Whadio could not release a recording download URL.");
      });
    }
    pending -= 1;
  }
}

async function record(tabId, streamId) {
  pending += 1;
  let failed = true;
  try {
    await offscreen();
    const reply = await chrome.runtime.sendMessage({
      target: "offscreen",
      type: "record",
      tabId,
      streamId,
    });
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
    failed = Boolean(reply.error);
    return reply;
  } finally {
    pending -= 1;
    // A start that failed leaves nothing in the document; a live recording closes it when it ends.
    if (failed) {
      await closeOffscreenIfIdle().catch(() => {});
    }
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

function shouldGiveUp(failure, attempt) {
  return attempt + 1 >= RETRIES || failure.status === 401 || failure.status === 404;
}

// One recording: opens a capture, uploads its chunks in order as they fill, resumes from what the
// server already holds after a failure, and completes it once the tab stops sending audio.
class Upload {
  constructor(startedAt, offscreen, owner) {
    this.id = crypto.randomUUID();
    this.owner = owner;
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
        await this.uploadPending();
        return;
      } catch (failure) {
        if (shouldGiveUp(failure, attempt)) {
          this.failed = true;
          return;
        }
        await pause(attempt);
        await this.syncReceived();
      }
    }
  }

  async uploadPending() {
    for (const [seq, chunk] of this.chunks.entries()) {
      if (!this.uploaded.has(seq)) {
        await this.uploadChunk(seq, chunk);
      }
    }
  }

  async uploadChunk(seq, chunk) {
    const form = new FormData();
    form.append("audio", chunk.audio, `${seq}.webm`);
    form.append("speaker_events", JSON.stringify(chunk.events));
    await api("PUT", `/captures/${this.capture.id}/chunks/${seq}`, form);
    this.uploaded.add(seq);
  }

  // A response lost on the way may have stored a chunk; the server tells which it holds.
  async syncReceived() {
    if (!this.capture) {
      return;
    }
    const found = await api("GET", `/captures/${this.capture.id}`).catch(() => null);
    for (const seq of found?.received_seqs ?? []) {
      this.uploaded.add(seq);
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
    if (this.slices.length > 0) {
      await recovery.retain(this.recoverable());
      this.retained = true;
      await recovery.retry(this.id, await sessionOwner());
    }
  }

  recoverable() {
    return { id: this.id, startedAt: this.startedAt, slices: this.slices, owner: this.owner };
  }
}

// The recording under way in each tab, which the tab's speaker names join.
const uploads = new Map();

async function refreshRecovery() {
  try {
    const recordings = await recovery.list();
    await chrome.action.setBadgeText({ text: recordings.length > 0 ? "!" : "" });
    await chrome.storage.local.set({ recoveryChangedAt: Date.now() });
  } catch {
    console.warn("Whadio could not update recording recovery status.");
    await chrome.action.setBadgeText({ text: "!" }).catch(() => {});
  }
}

const recovery = new RecordingRecovery(recoveryStore, saveLocally, refreshRecovery);

async function finishRecording(tabId, upload) {
  pending += 1;
  try {
    await upload.finish();
  } catch {
    console.warn("Whadio could not save a recording. Open the extension to retry or discard it.");
    if (upload.slices.length > 0 && !upload.retained) {
      await recovery.retain(upload.recoverable());
    }
    await chrome.tabs
      .sendMessage(tabId, {
        type: "show-error",
        error:
          "Your recording could not be saved. Open Whadio in the toolbar to retry or discard it.",
      })
      .catch(() => {});
  } finally {
    pending -= 1;
    await closeOffscreenIfIdle().catch(() => {
      console.warn("Whadio could not close its idle recording document.");
    });
  }
}

void refreshRecovery();

chrome.runtime.onMessage.addListener((message, sender, sendResponse) => {
  if (!["recovery-list", "recovery-retry", "recovery-discard"].includes(message.type)) {
    return false;
  }
  // A Meet content script must not list, download or discard the browser profile's local audio.
  if (sender.url !== chrome.runtime.getURL("popup.html")) {
    sendResponse({ error: "Open the Whadio popup to recover recordings." });
    return false;
  }
  const act = async () => {
    const owner = await sessionOwner();
    if (!owner) {
      return { recordings: [], locked: (await recovery.list()).length > 0 };
    }
    if (message.type !== "recovery-list") {
      if (typeof message.id !== "string") {
        throw new Error("A recording is required.");
      }
      if (message.type === "recovery-retry") {
        try {
          await recovery.retry(message.id, owner);
        } finally {
          await closeOffscreenIfIdle().catch(() => {
            console.warn("Whadio could not close its idle recording document.");
          });
        }
      } else {
        await recovery.discard(message.id, owner);
      }
    }
    return { recordings: await recovery.list(owner) };
  };
  act().then(sendResponse, () =>
    sendResponse({
      error: "The recording could not be recovered. Try again; it has not been discarded.",
    }),
  );
  return true;
});

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
  const owner = await sessionOwner();
  if (!owner) {
    return;
  }
  const upload = new Upload(Date.now(), !port.sender?.tab, owner);
  uploads.set(tabId, upload);
  // Opened at once rather than with the first chunk, so the meeting's time is when recording began.
  upload.queue = upload.queue.then(() => upload.send());
  port.onMessage.addListener((message) => upload.add(message.audio));
  port.onDisconnect.addListener(() => {
    uploads.delete(tabId);
    // The tab may already be closed, so telling it and clearing its badge may fail.
    chrome.tabs.sendMessage(tabId, { type: "stopped" }).catch(() => {});
    chrome.action.setBadgeText({ tabId, text: null }).catch(() => {});
    void finishRecording(tabId, upload).catch(() => {
      console.warn("Whadio could not finish recording recovery. Open the extension to check it.");
    });
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
    record(message.tabId, message.streamId).then(sendResponse, (failure) =>
      sendResponse({ error: failure.message }),
    );
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
    await chrome.tabs
      .sendMessage(tab.id, { type: "show-error", error: failure.message })
      .catch(() => {});
  }
});
