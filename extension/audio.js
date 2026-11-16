globalThis.whadioAudio = {
  base64(buffer) {
    const bytes = new Uint8Array(buffer);
    let binary = "";
    for (let offset = 0; offset < bytes.length; offset += 0x8000) {
      binary += String.fromCharCode(...bytes.subarray(offset, offset + 0x8000));
    }
    return btoa(binary);
  },

  record(tab, microphone, name, playBack) {
    let context;
    let port;
    const release = () => {
      for (const stream of [tab, microphone]) {
        for (const track of stream.getTracks()) {
          track.stop();
        }
      }
      void context?.close();
    };
    try {
      context = new AudioContext();
      const mix = context.createMediaStreamDestination();
      const call = context.createMediaStreamSource(tab);
      if (playBack) {
        call.connect(context.destination);
      }
      call.connect(mix);
      context.createMediaStreamSource(microphone).connect(mix);

      // The background uploads the audio as it arrives and completes the recording when this port disconnects.
      port = chrome.runtime.connect({ name });
      const recorder = new MediaRecorder(mix.stream, { mimeType: "audio/webm;codecs=opus" });
      let sent = Promise.resolve();
      recorder.addEventListener("dataavailable", (event) => {
        sent = sent.then(async () =>
          port.postMessage({
            audio: globalThis.whadioAudio.base64(await event.data.arrayBuffer()),
          }),
        );
      });
      recorder.addEventListener(
        "stop",
        () => {
          release();
          void sent.then(() => port.disconnect());
        },
        { once: true },
      );
      // A restarted service worker has lost this recording's upload, so nothing could stop it or take its audio.
      port.onDisconnect.addListener(() => {
        if (recorder.state !== "inactive") {
          recorder.stop();
        }
      });
      recorder.start(1000);
      return recorder;
    } catch (failure) {
      release();
      port?.disconnect();
      throw failure;
    }
  },
};
