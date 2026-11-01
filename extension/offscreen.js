chrome.runtime.onMessage.addListener((message, _sender, sendResponse) => {
  if (message.target !== "offscreen") {
    return false;
  }
  const parts = message.chunks.map((chunk) =>
    Uint8Array.from(atob(chunk), (char) => char.charCodeAt(0)),
  );
  sendResponse({ url: URL.createObjectURL(new Blob(parts, { type: "audio/webm" })) });
  return false;
});
