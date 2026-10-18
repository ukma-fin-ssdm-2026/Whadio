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

async function save(tabId, startedAt, chunks) {
  // The tab may already be closed, so this may fail, and the recording is saved regardless.
  chrome.action.setBadgeText({ tabId, text: "" }).catch(() => {});
  if (chunks.length === 0) {
    return;
  }
  // A service worker cannot make a blob URL, so an offscreen document turns the audio into one.
  if (!(await chrome.offscreen.hasDocument())) {
    await chrome.offscreen.createDocument({
      url: "offscreen.html",
      reasons: ["BLOBS"],
      justification: "Turns a finished recording into a file to download.",
    });
  }
  const { url } = await chrome.runtime.sendMessage({ target: "offscreen", chunks });
  const stamp = new Date(startedAt).toISOString().slice(0, 19).replaceAll(":", "-");
  const downloadId = await chrome.downloads.download({ url, filename: `whadio-${stamp}.webm` });
  await downloaded(downloadId);
  await chrome.offscreen.closeDocument();
}

chrome.runtime.onConnect.addListener(async (port) => {
  if (port.name !== "recording" || !port.sender?.tab) {
    return;
  }
  const tabId = port.sender.tab.id;
  const startedAt = Date.now();
  const chunks = [];
  port.onMessage.addListener((chunk) => chunks.push(chunk));
  port.onDisconnect.addListener(() => save(tabId, startedAt, chunks));

  await chrome.action.setBadgeText({ tabId, text: "REC" });
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
  } else if (!status.consented) {
    await chrome.tabs.sendMessage(tab.id, { type: "ask-consent" });
  } else {
    const streamId = await chrome.tabCapture.getMediaStreamId({ targetTabId: tab.id, consumerTabId: tab.id });
    await chrome.tabs.sendMessage(tab.id, { type: "start", streamId });
  }
});
