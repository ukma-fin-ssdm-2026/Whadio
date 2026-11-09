const ACTION_ERROR_MS = 2500;

export function showRecovery() {
  const section = document.getElementById("recovery");
  const list = document.getElementById("recovery-list");
  const error = document.getElementById("recovery-error");
  let revision = 0;
  let sessionRevision = 0;
  let errorTimer;

  async function request(type, id) {
    const reply = await chrome.runtime.sendMessage({ type, id });
    if (!reply || reply.error) {
      throw new Error(
        "The recording could not be recovered. Try again; it has not been discarded.",
      );
    }
    return reply;
  }

  function clearError() {
    clearTimeout(errorTimer);
    errorTimer = undefined;
    error.hidden = true;
  }

  function render({ recordings, locked }) {
    if (locked) {
      clearError();
      error.textContent =
        "Sign in to the original account and server to recover your saved recordings.";
      error.hidden = false;
    } else {
      error.hidden = errorTimer === undefined;
    }
    section.hidden = recordings.length === 0 && error.hidden;
    list.replaceChildren(
      ...recordings.map(({ id, startedAt, temporary, busy }) => {
        const row = document.createElement("li");
        const description = document.createElement("p");
        description.textContent = `Recording from ${new Date(startedAt).toLocaleString()}`;
        row.append(description);
        if (temporary) {
          const warning = document.createElement("p");
          warning.className = "error";
          warning.textContent =
            "Local storage is unavailable. Retry now; this copy will not survive a restart.";
          row.append(warning);
        }
        for (const [label, type] of [
          ["Retry download", "recovery-retry"],
          ["Discard", "recovery-discard"],
        ]) {
          const button = document.createElement("button");
          button.type = "button";
          button.textContent = label;
          button.disabled = busy;
          button.addEventListener("click", async () => {
            if (
              type === "recovery-discard" &&
              !window.confirm("Discard this local recording permanently?")
            ) {
              return;
            }
            for (const control of row.querySelectorAll("button")) {
              control.disabled = true;
            }
            const current = revision;
            const currentSession = sessionRevision;
            try {
              clearError();
              const reply = await request(type, id);
              if (current === revision) {
                render(reply);
              }
            } catch {
              if (currentSession !== sessionRevision) {
                return;
              }
              clearError();
              showError();
              errorTimer = setTimeout(() => {
                clearError();
                section.hidden = list.childElementCount === 0;
              }, ACTION_ERROR_MS);
              for (const control of row.querySelectorAll("button")) {
                control.disabled = false;
              }
            }
          });
          row.append(button);
        }
        return row;
      }),
    );
  }

  function showError() {
    section.hidden = false;
    error.textContent =
      "Whadio could not access or save a recording. Open the popup again or retry. Nothing was discarded.";
    error.hidden = false;
  }

  async function refresh() {
    const current = ++revision;
    try {
      const reply = await request("recovery-list");
      if (current === revision) {
        render(reply);
      }
    } catch {
      if (current === revision) {
        clearError();
        showError();
      }
    }
  }

  chrome.storage.onChanged.addListener((changes, area) => {
    if (area === "session") {
      sessionRevision += 1;
      clearError();
    }
    if ((area === "local" && "recoveryChangedAt" in changes) || area === "session") {
      list.replaceChildren();
      void refresh();
    }
  });
  return refresh();
}
