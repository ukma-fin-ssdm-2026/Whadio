const MEET_CALL = /^https:\/\/meet\.google\.com\/[a-z]{3}-[a-z]{4}-[a-z]{3}(?:[/?#]|$)/;

const sections = ["not-meet", "idle", "recording"].map((id) => document.getElementById(id));
const consent = document.getElementById("consent");
const start = document.getElementById("start");
const stop = document.getElementById("stop");
const elapsed = document.getElementById("elapsed");
const error = document.getElementById("error");

function show(id) {
  for (const section of sections) {
    section.hidden = section.id !== id;
  }
}

function showError(message) {
  error.textContent = message;
  error.hidden = message === "";
}

function tick(startedAt) {
  const seconds = Math.floor((Date.now() - startedAt) / 1000);
  const minutes = Math.floor(seconds / 60);
  elapsed.textContent = `${minutes}:${String(seconds % 60).padStart(2, "0")}`;
}

function showRecording(startedAt) {
  show("recording");
  tick(startedAt);
  setInterval(() => tick(startedAt), 1000);
}

const [tab] = await chrome.tabs.query({ active: true, currentWindow: true });

if (tab?.url && MEET_CALL.test(tab.url)) {
  await chrome.scripting.executeScript({ target: { tabId: tab.id }, files: ["recorder.js"] });
  const { startedAt } = await chrome.tabs.sendMessage(tab.id, { type: "status" });
  if (startedAt) {
    showRecording(startedAt);
  } else {
    show("idle");
  }
} else {
  show("not-meet");
}

consent.addEventListener("change", () => {
  start.disabled = !consent.checked;
});

start.addEventListener("click", async () => {
  showError("");
  start.disabled = true;
  const streamId = await chrome.tabCapture.getMediaStreamId({
    targetTabId: tab.id,
    consumerTabId: tab.id,
  });
  const reply = await chrome.tabs.sendMessage(tab.id, { type: "start", streamId });
  if (reply.error) {
    showError(reply.error);
    start.disabled = false;
    return;
  }
  showRecording(reply.startedAt);
});

stop.addEventListener("click", async () => {
  stop.disabled = true;
  await chrome.tabs.sendMessage(tab.id, { type: "stop" });
  window.close();
});
