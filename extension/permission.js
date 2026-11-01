// The offscreen document that records cannot ask for the microphone, so this page asks once for the extension.
const status = document.getElementById("status");
try {
  const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
  for (const track of stream.getTracks()) {
    track.stop();
  }
  status.textContent = "Microphone allowed. Close this tab and start recording again.";
} catch {
  status.textContent =
    "Whadio cannot record your voice without the microphone. Allow it from the address bar and reload this page.";
}
