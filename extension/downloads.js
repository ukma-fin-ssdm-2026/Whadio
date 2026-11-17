export async function downloadFile(options) {
  let downloadId;
  let finish;
  const ended = new Promise((resolve) => {
    finish = resolve;
  });
  function observe(state) {
    if (state === "complete" || state === "interrupted") {
      finish(state);
    }
  }
  function changed(delta) {
    if (delta.id === downloadId) {
      observe(delta.state?.current);
    }
  }
  // A small local file can finish before download() returns its ID.
  chrome.downloads.onChanged.addListener(changed);
  try {
    downloadId = await chrome.downloads.download(options);
    const [download] = await chrome.downloads.search({ id: downloadId });
    if (!download) {
      throw new Error("The local download is no longer available.");
    }
    observe(download.state);
    if ((await ended) !== "complete") {
      throw new Error("The local download was interrupted. Retry it from Whadio.");
    }
  } finally {
    chrome.downloads.onChanged.removeListener(changed);
  }
}
