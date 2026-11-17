// Loaded as a classic script in both the Meet content script and the offscreen document.
globalThis.whadioRecordingReady = async (port) => {
  let onMessage;
  let onDisconnect;
  let timeout;
  try {
    return await new Promise((resolve, reject) => {
      onMessage = (message) => {
        if (message.type === "recording-ready") {
          resolve(message.startedAt);
        } else if (message.type === "recording-rejected") {
          reject(new Error(message.error));
        }
      };
      onDisconnect = () => reject(new Error("Whadio disconnected before recording started."));
      port.onMessage.addListener(onMessage);
      port.onDisconnect.addListener(onDisconnect);
      timeout = setTimeout(
        () => reject(new Error("Whadio did not confirm recording started.")),
        5000,
      );
    });
  } catch (failure) {
    port.disconnect();
    throw failure;
  } finally {
    clearTimeout(timeout);
    port.onMessage.removeListener(onMessage);
    port.onDisconnect.removeListener(onDisconnect);
  }
};
