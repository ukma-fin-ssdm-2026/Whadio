// Records the calls started from the popup or the shortcut. Capturing a tab silences it for the user, so the
// call has to be played back, and played back inside the captured tab it would be captured again and echo
// without end. This document is not captured, so the call plays from here. The recorders are keyed by tab.
const recordings = new Map();

async function microphoneRefused(failure) {
  if (failure.name === "NotFoundError") {
    return { error: "Whadio found no microphone. Connect one, then start again." };
  }
  if (failure.name !== "NotAllowedError") {
    throw failure;
  }
  const { state } = await navigator.permissions.query({ name: "microphone" });
  if (state === "prompt") {
    // This document cannot ask for the microphone; the background opens a page that can.
    return {
      error: "Allow Whadio to use your microphone in the tab that opened, then start again.",
      microphone: true,
    };
  }
  if (state === "denied") {
    return {
      error:
        "Whadio is blocked from your microphone. Allow it for Whadio in Chrome's site settings, then start again.",
    };
  }
  return {
    error: "Your system keeps Chrome from using the microphone. Allow it there, then start again.",
  };
}

async function record(tabId, streamId) {
  const tab = await navigator.mediaDevices.getUserMedia({
    audio: { mandatory: { chromeMediaSource: "tab", chromeMediaSourceId: streamId } },
  });
  let microphone;
  try {
    // With gain control on, this stream and Meet's would both move the system microphone volume.
    microphone = await navigator.mediaDevices.getUserMedia({ audio: { autoGainControl: false } });
  } catch (failure) {
    // A captured tab stays silenced until its tracks stop.
    for (const track of tab.getTracks()) {
      track.stop();
    }
    return await microphoneRefused(failure);
  }

  const startedAt = Date.now();
  const recorder = globalThis.whadioAudio.record(
    tab,
    microphone,
    `recording:${tabId}:${startedAt}`,
    true,
  );
  recorder.addEventListener("stop", () => recordings.delete(tabId), { once: true });
  // The capture ends by itself only when the tab closes; a reload or a navigation is stopped by the background.
  tab.getAudioTracks()[0].addEventListener("ended", () => {
    if (recorder.state !== "inactive") {
      recorder.stop();
    }
  });
  recordings.set(tabId, recorder);
  return { startedAt };
}

chrome.runtime.onMessage.addListener((message, _sender, sendResponse) => {
  if (message.target !== "offscreen") {
    return false;
  }
  if (message.type === "record") {
    record(message.tabId, message.streamId).then(sendResponse, (failure) =>
      sendResponse({ error: failure.message }),
    );
    return true;
  }
  if (message.type === "stop") {
    const recorder = recordings.get(message.tabId);
    if (recorder && recorder.state !== "inactive") {
      recorder.stop();
    }
    return false;
  }
  // A service worker cannot make a blob URL, so a recording the server did not take becomes one here,
  // released once its download ends.
  if (message.type === "blob") {
    const parts = message.chunks.map((chunk) =>
      Uint8Array.from(atob(chunk), (char) => char.charCodeAt(0)),
    );
    sendResponse({ url: URL.createObjectURL(new Blob(parts, { type: "audio/webm" })) });
    return false;
  }
  if (message.type === "revoke") {
    URL.revokeObjectURL(message.url);
    sendResponse({});
  }
  return false;
});
