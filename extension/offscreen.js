// Records the calls started from the popup or the shortcut. Capturing a tab silences it for the user, so the
// call has to be played back, and played back inside the captured tab it would be captured again and echo
// without end. This document is not captured, so the call plays from here. The recorders are keyed by tab.
const recordings = new Map();

function base64(buffer) {
  const bytes = new Uint8Array(buffer);
  let binary = "";
  for (let offset = 0; offset < bytes.length; offset += 0x8000) {
    binary += String.fromCharCode(...bytes.subarray(offset, offset + 0x8000));
  }
  return btoa(binary);
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
    if (failure.name !== "NotAllowedError") {
      throw failure;
    }
    // This document cannot ask for the microphone; the background opens a page that can.
    return { error: "Allow Whadio to use your microphone in the tab that opened, then start again.", microphone: true };
  }

  const context = new AudioContext();
  const mix = context.createMediaStreamDestination();
  const call = context.createMediaStreamSource(tab);
  call.connect(context.destination);
  call.connect(mix);
  context.createMediaStreamSource(microphone).connect(mix);

  // The background uploads the audio as it arrives and completes the recording when this port disconnects.
  const port = chrome.runtime.connect({ name: `recording:${tabId}` });
  let sent = Promise.resolve();
  const recorder = new MediaRecorder(mix.stream, { mimeType: "audio/webm;codecs=opus" });
  recorder.addEventListener("dataavailable", (event) => {
    sent = sent.then(async () => port.postMessage({ audio: base64(await event.data.arrayBuffer()) }));
  });
  recorder.addEventListener(
    "stop",
    () => {
      recordings.delete(tabId);
      for (const stream of [tab, microphone]) {
        for (const track of stream.getTracks()) {
          track.stop();
        }
      }
      void context.close();
      void sent.then(() => port.disconnect());
    },
    { once: true },
  );
  // The capture ends by itself when the tab closes or leaves Meet.
  tab.getAudioTracks()[0].addEventListener("ended", () => {
    if (recorder.state !== "inactive") {
      recorder.stop();
    }
  });
  recorder.start(1000);
  recordings.set(tabId, recorder);
  return { startedAt: Date.now() };
}

chrome.runtime.onMessage.addListener((message, _sender, sendResponse) => {
  if (message.target !== "offscreen") {
    return false;
  }
  if (message.type === "record") {
    record(message.tabId, message.streamId).then(sendResponse, (failure) => sendResponse({ error: failure.message }));
    return true;
  }
  if (message.type === "stop") {
    const recorder = recordings.get(message.tabId);
    if (recorder && recorder.state !== "inactive") {
      recorder.stop();
    }
    return false;
  }
  // A service worker cannot make a blob URL, so a recording the server did not take becomes one here.
  const parts = message.chunks.map((chunk) => Uint8Array.from(atob(chunk), (char) => char.charCodeAt(0)));
  sendResponse({ url: URL.createObjectURL(new Blob(parts, { type: "audio/webm" })) });
  return false;
});
