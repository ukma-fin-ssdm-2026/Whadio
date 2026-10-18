import { api, originPattern, signIn, signOut, signedIn } from "./server.js";

const MEET_CALL = /^https:\/\/meet\.google\.com\/[a-z]{3}-[a-z]{4}-[a-z]{3}(?:[/?#]|$)/;

const sections = ["not-meet", "idle", "recording"].map((id) => document.getElementById(id));
const signInForm = document.getElementById("sign-in");
const account = document.getElementById("account");
const destination = document.getElementById("destination");
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

// --- Account and destination ---

async function showAccount() {
  if (!(await signedIn())) {
    signInForm.hidden = false;
    account.hidden = true;
    return false;
  }
  signInForm.hidden = true;
  account.hidden = false;
  const { name, destination: chosen } = await chrome.storage.local.get(["name", "destination"]);
  document.getElementById("name").textContent = name ?? "";
  const page = await api("GET", "/captures/destinations?limit=100");
  destination.replaceChildren(
    ...page.items.flatMap((workspace) =>
      workspace.folders.map((folder) => {
        const value = JSON.stringify({ workspace_id: workspace.workspace_id, folder_id: folder.id });
        const option = new Option(`${workspace.name} / ${folder.name}`, value);
        option.selected = chosen
          ? chosen.folder_id === folder.id
          : workspace.is_personal && folder.is_default;
        return option;
      }),
    ),
  );
  await chrome.storage.local.set({ destination: JSON.parse(destination.value) });
  return true;
}

signInForm.addEventListener("submit", async (event) => {
  event.preventDefault();
  showError("");
  const server = new URL(document.getElementById("server").value).origin;
  // Asked inside the click, as Chrome requires, and only for the server the user names.
  if (!(await chrome.permissions.request({ origins: [originPattern(server)] }))) {
    showError("Whadio needs access to the server to upload recordings.");
    return;
  }
  try {
    await signIn(server, document.getElementById("email").value, document.getElementById("password").value);
    await showAccount();
  } catch (failure) {
    showError(failure.message);
  }
});

document.getElementById("sign-out").addEventListener("click", async () => {
  await signOut();
  await showAccount();
});

destination.addEventListener("change", () => chrome.storage.local.set({ destination: JSON.parse(destination.value) }));

// --- Recording ---

const [tab] = await chrome.tabs.query({ active: true, currentWindow: true });

let ready = false;
try {
  ready = await showAccount();
} catch (failure) {
  showError(failure.message);
}

if (!tab?.url || !MEET_CALL.test(tab.url)) {
  show("not-meet");
} else {
  await chrome.scripting.executeScript({ target: { tabId: tab.id }, files: ["recorder.js"] });
  await chrome.tabs.sendMessage(tab.id, { type: "hide-card" });
  const { startedAt } = await chrome.tabs.sendMessage(tab.id, { type: "status" });
  if (startedAt) {
    showRecording(startedAt);
  } else if (ready) {
    show("idle");
  }
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
