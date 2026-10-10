const data = {
  user: {
    name: "Margaret Hamilton",
    email: "margaret@whadio.dev",
  },
  workspaces: [
    {
      id: "7b1e9c40-2d3f-4a5b-8c6d-0e1f2a3b4c5d",
      name: "Whadio team",
      role: "owner",
      memberCount: 3,
      defaultPreset: "detailed",
      notesProvider: "whadio",
    },
    {
      id: "1c2d3e4f-5a6b-4c7d-8e9f-0a1b2c3d4e5f",
      name: "Margaret Hamilton",
      role: "owner",
      memberCount: 1,
      defaultPreset: "summary",
      notesProvider: "whadio",
    },
  ],
  meetings: [
    {
      id: "0a1b2c3d-4e5f-4a6b-8c7d-9e0f1a2b3c4d",
      workspaceId: "7b1e9c40-2d3f-4a5b-8c6d-0e1f2a3b4c5d",
      name: "Lab 3 architecture follow-up",
      recordedAt: "2026-09-27T13:30:00Z",
      state: "queued",
      source: "upload",
      durationSeconds: null,
      accessMode: "workspace",
      preset: "detailed",
    },
    {
      id: "5d1f0c2a-9b8e-4f7d-a6c5-b4d3e2f1a0b9",
      workspaceId: "7b1e9c40-2d3f-4a5b-8c6d-0e1f2a3b4c5d",
      name: "Lab 3 architecture planning",
      recordedAt: "2026-09-24T19:02:00Z",
      state: "processed",
      source: "upload",
      durationSeconds: 1632,
      accessMode: "workspace",
      preset: "detailed",
    },
    {
      id: "8c7b6a59-4d3e-4f2a-b1c0-d9e8f7a6b5c4",
      workspaceId: "7b1e9c40-2d3f-4a5b-8c6d-0e1f2a3b4c5d",
      name: "Lab 2 requirements review",
      recordedAt: "2026-09-19T18:40:00Z",
      state: "processed",
      source: "upload",
      durationSeconds: 2410,
      accessMode: "workspace",
      preset: "summary",
    },
    {
      id: "6e5d4c3b-2a19-4807-96f5-e4d3c2b1a090",
      workspaceId: "1c2d3e4f-5a6b-4c7d-8e9f-0a1b2c3d4e5f",
      name: "Thesis consultation",
      recordedAt: "2026-09-25T16:30:00Z",
      state: "processed",
      source: "upload",
      durationSeconds: 2730,
      accessMode: "workspace",
      preset: "summary",
    },
  ],
  transcript: {
    language: "uk",
    modelName: "parakeet-tdt-0.6b-v3",
    speakers: {
      lead: "Speaker 02",
      reviewer: "Speaker 00",
      teammate: "Speaker 04",
    },
    segments: [
      {
        startSeconds: 133,
        endSeconds: 150,
        speakerId: "lead",
        text: "Що по завданню для лаби? Треба обрати архітектурний стиль, створити діаграму компонентів, описати інтерфейси між компонентами і додати діаграму розгортання.",
      },
      {
        startSeconds: 204,
        endSeconds: 215,
        speakerId: "lead",
        text: "На практиці обговорювали більше мікросервіси, але я погоджуюся, що це трохи overkill для нашого проєкту. Можливо, нам треба щось простіше.",
      },
      {
        startSeconds: 389,
        endSeconds: 465,
        speakerId: "lead",
        text: "Можливо, це може бути модульний моноліт. Для GPU-частини можна мати окремі ML workers для транскрипції і генерації нотаток, з окремим lifecycle.",
      },
      {
        startSeconds: 563,
        endSeconds: 614,
        speakerId: "lead",
        text: "По факту це моноліт, але з кількома entry points: основна web/backend app, broker і ML workers, які можуть запускатися на іншій машині.",
      },
      {
        startSeconds: 643,
        endSeconds: 676,
        speakerId: "reviewer",
        text: "Це як моноліт, але різні компоненти. Треба мати загальну ідею, що ми хочемо, а імплементацію можна уточнювати пізніше.",
      },
      {
        startSeconds: 791,
        endSeconds: 804,
        speakerId: "lead",
        text: "Узгодили, що це буде плюс-мінус моноліт з різними сервісами в Docker Compose. Можна буде розглядати і одну машину, і багато машин.",
      },
      {
        startSeconds: 1056,
        endSeconds: 1076,
        speakerId: "lead",
        text: "Я хотів би бути керівником архітектури: вибір стилю і діаграми компонентів. Deployment diagram теж можна взяти сюди.",
      },
      {
        startSeconds: 1200,
        endSeconds: 1250,
        speakerId: "lead",
        text: "Доменна модель ближча до бізнес-вимог і коду застосунку, але для цієї лабораторної, можливо, ER-моделі буде достатньо, щоб не мучитись.",
      },
      {
        startSeconds: 1550,
        endSeconds: 1574,
        speakerId: "lead",
        text: "Пропоную зустрітися в суботу о 13:30 на годинку і уточнити розподіл ролей, хто чим займається.",
      },
    ],
  },
  notes: {
    preset: "detailed",
    provider: "whadio",
    modelName: "gemma-3-12b-it",
    summary: "Команда розібрала вимоги Lab 3 і погодила базовий архітектурний напрям: модульний моноліт із кількома entry points, message broker та окремими ML workers для транскрипції й генерації нотаток. Мікросервіси визнали надмірними для масштабу лабораторної.",
    actionItems: [
      "Зафіксувати архітектурний стиль як modular monolith з окремими workers.",
      "Підготувати component diagram, deployment diagram та sequence diagram.",
      "Окремо визначити модель даних: ER або domain model.",
      "Зустрітися в суботу о 13:30 для уточнення ролей і деталей.",
    ],
    contextMeetings: ["Lab 2 requirements review"],
  },
};

const state = {
  view: "home",
  workspaceId: data.workspaces[0].id,
  selectedMeetingId: "",
  search: "",
  stateFilter: "all",
  transcriptSearch: "",
  meetingMode: "notes",
  workspacesOpen: false,
  expandedWorkspaceIds: data.workspaces.map((workspace) => workspace.id),
};

const elements = {
  homeButton: document.querySelector("#homeButton"),
  meetingsButton: document.querySelector("#meetingsButton"),
  workspacesButton: document.querySelector("#workspacesButton"),
  workspaceTree: document.querySelector("#workspaceTree"),
  breadcrumbs: document.querySelector("#breadcrumbs"),
  topbar: document.querySelector(".topbar"),
  workspaceTitle: document.querySelector("#workspaceTitle"),
  roleLabel: document.querySelector("#roleLabel"),
  providerButton: document.querySelector("#providerButton"),
  uploadForm: document.querySelector("#uploadForm"),
  recordingFile: document.querySelector("#recordingFile"),
  meetingName: document.querySelector("#meetingName"),
  presetSelect: document.querySelector("#presetSelect"),
  homeView: document.querySelector("#homeView"),
  workspaceGrid: document.querySelector("#workspaceGrid"),
  quickStart: document.querySelector("#quickStart"),
  workspaceView: document.querySelector("#workspaceView"),
  meetingViewBar: document.querySelector("#meetingViewBar"),
  meetingDetailView: document.querySelector("#meetingDetailView"),
  meetingNotes: document.querySelector("#meetingNotes"),
  transcriptPanel: document.querySelector(".transcript-panel"),
  transcriptSearch: document.querySelector("#transcriptSearch"),
  transcriptStream: document.querySelector("#transcriptStream"),
  searchInput: document.querySelector("#searchInput"),
  stateFilter: document.querySelector("#stateFilter"),
  meetingList: document.querySelector("#meetingList"),
  meetingSectionEyebrow: document.querySelector(".section-heading .eyebrow"),
  meetingTemplate: document.querySelector("#meetingTemplate"),
};

function currentWorkspace() {
  return data.workspaces.find((workspace) => workspace.id === state.workspaceId);
}

function workspaceMeetings() {
  const meetings = state.view === "meetings"
    ? data.meetings
    : data.meetings.filter((meeting) => meeting.workspaceId === state.workspaceId);

  return meetings
    .filter((meeting) => meeting.name.toLowerCase().includes(state.search.toLowerCase()))
    .filter((meeting) => state.stateFilter === "all" || meeting.state === state.stateFilter)
    .sort((left, right) => new Date(right.recordedAt) - new Date(left.recordedAt));
}

function selectedMeeting() {
  return data.meetings.find((meeting) => meeting.id === state.selectedMeetingId);
}

function formatDate(value) {
  return new Intl.DateTimeFormat("en", {
    dateStyle: "medium",
    timeStyle: "short",
  }).format(new Date(value));
}

function formatDuration(seconds) {
  if (seconds === null) {
    return "Duration pending";
  }

  const minutes = Math.floor(seconds / 60);
  const remainder = seconds % 60;
  return `${minutes}m ${remainder}s`;
}

function sentenceCase(value) {
  return value.charAt(0).toUpperCase() + value.slice(1);
}

function openWorkspace(workspaceId) {
  state.view = "workspace";
  state.workspaceId = workspaceId;
  state.workspacesOpen = true;
  if (!state.expandedWorkspaceIds.includes(workspaceId)) {
    state.expandedWorkspaceIds.push(workspaceId);
  }
  state.selectedMeetingId = "";
  state.search = "";
  state.stateFilter = "all";
  elements.searchInput.value = "";
  elements.stateFilter.value = "all";
  render();
}

function openMeeting(meetingId) {
  const meeting = data.meetings.find((item) => item.id === meetingId);
  if (meeting) {
    state.workspaceId = meeting.workspaceId;
    state.workspacesOpen = true;
    if (!state.expandedWorkspaceIds.includes(meeting.workspaceId)) {
      state.expandedWorkspaceIds.push(meeting.workspaceId);
    }
  }
  state.selectedMeetingId = meetingId;
  state.view = "meeting";
  state.transcriptSearch = "";
  state.meetingMode = "notes";
  elements.transcriptSearch.value = "";
  render();
}

function renderWorkspaceCards() {
  elements.workspaceGrid.replaceChildren(
    ...data.workspaces.map((workspace) => {
      const button = document.createElement("button");
      button.type = "button";
      button.className = "workspace-card";
      const meetings = data.meetings.filter((meeting) => meeting.workspaceId === workspace.id);
      const activeCount = meetings.filter((meeting) =>
        ["queued", "processing"].includes(meeting.state),
      ).length;
      button.innerHTML = `
        <span class="workspace-card-icon" aria-hidden="true">${workspace.name.charAt(0)}</span>
        <span>
          <strong>${workspace.name}</strong>
          <small>${sentenceCase(workspace.role)} - ${workspace.memberCount} members</small>
        </span>
        <span class="workspace-card-meta">${meetings.length} meetings, ${activeCount} active</span>
      `;
      button.addEventListener("click", () => openWorkspace(workspace.id));
      return button;
    }),
  );
}

function renderWorkspaceTree() {
  elements.workspaceTree.hidden = !state.workspacesOpen;
  elements.workspaceTree.replaceChildren(
    ...data.workspaces.map((workspace) => {
      const section = document.createElement("section");
      section.className = "workspace-tree-item";
      const isActiveWorkspace = workspace.id === state.workspaceId;
      const isExpandedWorkspace = state.expandedWorkspaceIds.includes(workspace.id);
      const meetings = data.meetings
        .filter((meeting) => meeting.workspaceId === workspace.id)
        .sort((left, right) => new Date(right.recordedAt) - new Date(left.recordedAt));

      const workspaceButton = document.createElement("button");
      workspaceButton.type = "button";
      workspaceButton.className = `workspace-tree-button${isActiveWorkspace ? " is-active" : ""}`;
      workspaceButton.innerHTML = `
        <span>${workspace.name}</span>
        <small>${meetings.length}</small>
      `;
      workspaceButton.addEventListener("click", () => openWorkspace(workspace.id));
      section.append(workspaceButton);

      const list = document.createElement("div");
      list.className = "workspace-transcripts";
      list.hidden = !isExpandedWorkspace;

      for (const meeting of meetings) {
        const meetingButton = document.createElement("button");
        meetingButton.type = "button";
        meetingButton.className = `transcript-link${state.view === "meeting" && meeting.id === state.selectedMeetingId ? " is-active" : ""}`;
        meetingButton.innerHTML = `
          <span>${meeting.name}</span>
          <small>${sentenceCase(meeting.state)}</small>
        `;
        meetingButton.addEventListener("click", () => openMeeting(meeting.id));
        list.append(meetingButton);
      }

      section.append(list);
      return section;
    }),
  );
}

function renderSummary() {
  const workspace = currentWorkspace();

  elements.homeButton.classList.toggle("is-active", state.view === "home");
  elements.meetingsButton.classList.toggle("is-active", state.view === "meetings");
  elements.workspacesButton.classList.toggle("is-active", state.workspacesOpen);
  elements.homeView.hidden = state.view !== "home";
  elements.quickStart.hidden = state.view !== "workspace";
  elements.workspaceView.hidden = !["workspace", "meetings"].includes(state.view);
  elements.meetingViewBar.hidden = state.view !== "meeting";
  elements.meetingDetailView.hidden = state.view !== "meeting";
  elements.topbar.hidden = state.view === "meeting";
  elements.providerButton.hidden = state.view !== "workspace";
  elements.roleLabel.hidden = false;
  elements.meetingSectionEyebrow.hidden = state.view === "meetings";

  if (state.view === "home") {
    elements.workspaceTitle.textContent = "Workspaces";
    elements.roleLabel.textContent = "Home";
    elements.breadcrumbs.innerHTML = "";
    return;
  }

  elements.providerButton.textContent = `Provider: ${sentenceCase(workspace.notesProvider)}`;
  if (state.view === "workspace" || state.view === "meetings") {
    elements.workspaceTitle.textContent = state.view === "meetings" ? "Meetings" : workspace.name;
    elements.roleLabel.textContent = `${sentenceCase(workspace.role)} workspace`;
    elements.roleLabel.hidden = state.view === "meetings";
    elements.breadcrumbs.innerHTML = `
      <button type="button" data-home>Home</button>
      <span>/</span>
      <span>${state.view === "meetings" ? "Meetings" : workspace.name}</span>
    `;
  } else {
    const meeting = selectedMeeting();
    elements.workspaceTitle.textContent = meeting?.name ?? "Meeting";
    elements.roleLabel.textContent = workspace.name;
    elements.breadcrumbs.innerHTML = `
      <button type="button" data-home>Home</button>
      <span>/</span>
      <button type="button" data-workspace>${workspace.name}</button>
      <span>/</span>
      <span>${meeting?.name ?? "Meeting"}</span>
    `;
  }

  const homeCrumb = elements.breadcrumbs.querySelector("[data-home]");
  homeCrumb.addEventListener("click", showHome);
  const workspaceCrumb = elements.breadcrumbs.querySelector("[data-workspace]");
  workspaceCrumb?.addEventListener("click", () => openWorkspace(state.workspaceId));
}

function renderMeetings() {
  const meetings = workspaceMeetings();

  if (meetings.length === 0) {
    elements.meetingList.innerHTML =
      '<div class="empty-state"><strong>No meetings found</strong><p>Change filters or queue a new upload.</p></div>';
    return;
  }

  elements.meetingList.replaceChildren(
    ...meetings.map((meeting) => {
      const fragment = elements.meetingTemplate.content.cloneNode(true);
      const button = fragment.querySelector(".meeting-item");
      const dot = fragment.querySelector(".state-dot");
      const title = fragment.querySelector("strong");
      const meta = fragment.querySelector("small");
      const pill = fragment.querySelector(".state-pill");

      button.classList.toggle("is-active", state.view === "meeting" && meeting.id === state.selectedMeetingId);
      button.addEventListener("click", () => {
        openMeeting(meeting.id);
      });
      dot.classList.add(meeting.state);
      title.textContent = meeting.name;
      meta.textContent = `${formatDate(meeting.recordedAt)} - ${sentenceCase(meeting.source)} - ${formatDuration(meeting.durationSeconds)}`;
      pill.classList.add(meeting.state);
      pill.textContent = meeting.state === "processed" ? "Open meeting" : sentenceCase(meeting.state);
      return fragment;
    }),
  );
}

function renderMeetingPage() {
  const meeting = selectedMeeting();

  if (!meeting) {
    elements.meetingNotes.innerHTML =
      '<div class="empty-state"><strong>No meeting selected</strong><p>Go back to the workspace and select a meeting.</p></div>';
    elements.transcriptStream.innerHTML = "";
    return;
  }

  const isProcessed = meeting.state === "processed";
  for (const button of elements.meetingViewBar.querySelectorAll("[data-meeting-mode]")) {
    button.classList.toggle("is-active", button.dataset.meetingMode === state.meetingMode);
  }
  elements.meetingDetailView.classList.toggle("recording-mode", state.meetingMode === "recording");
  elements.meetingDetailView.classList.toggle("notes-mode", state.meetingMode === "notes");
  elements.transcriptPanel.hidden = state.meetingMode !== "recording";
  elements.meetingNotes.innerHTML = `
    <header class="meeting-page-header">
      <div>
        <span class="eyebrow">${sentenceCase(meeting.state)} meeting</span>
        <h2>${meeting.name}</h2>
        <div class="detail-meta">
          <span class="meta-chip">${formatDate(meeting.recordedAt)}</span>
          <span class="meta-chip">${currentWorkspace().name}</span>
          <span class="meta-chip">${sentenceCase(meeting.source)}</span>
          <span class="meta-chip">${formatDuration(meeting.durationSeconds)}</span>
          <span class="meta-chip">${sentenceCase(meeting.accessMode)} access</span>
        </div>
      </div>
      <span class="state-pill ${meeting.state}">${sentenceCase(meeting.state)}</span>
    </header>
    ${
      isProcessed
        ? renderMeetingMode(meeting)
        : `<div class="empty-state"><strong>${sentenceCase(meeting.state)}</strong><p>The transcript and notes appear after the processing worker finishes.</p></div>`
    }
  `;
  if (state.meetingMode === "recording") {
    renderTranscript(meeting);
  }
}

function renderMeetingMode(meeting) {
  return state.meetingMode === "notes"
    ? renderNotes(meeting)
    : renderRecording(meeting);
}

function renderTranscript(meeting) {
  if (meeting.state !== "processed") {
    elements.transcriptStream.innerHTML =
      '<div class="empty-state"><strong>No transcript yet</strong><p>This meeting is still waiting for processing.</p></div>';
    return;
  }

  const query = state.transcriptSearch.trim().toLowerCase();
  const segments = data.transcript.segments.filter((segment) => {
    const speaker = data.transcript.speakers[segment.speakerId].toLowerCase();
    return query === "" || segment.text.toLowerCase().includes(query) || speaker.includes(query);
  });

  if (segments.length === 0) {
    elements.transcriptStream.innerHTML =
      '<div class="empty-state"><strong>No transcript matches</strong><p>Try another search term.</p></div>';
    return;
  }

  const rows = segments
    .map(
      (segment) => `
        <article class="transcript-row">
          <div class="speaker-line">
            <span class="speaker-avatar">${data.transcript.speakers[segment.speakerId].charAt(0)}</span>
            <strong>${data.transcript.speakers[segment.speakerId]}</strong>
            <time>${segment.startSeconds.toFixed(2)}s</time>
          </div>
          <p>${segment.text}</p>
        </article>
      `,
    )
    .join("");

  elements.transcriptStream.innerHTML = rows;
}

function renderNotes(meeting) {
  const items = data.notes.actionItems.map((item) => `<li>${item}</li>`).join("");
  const contexts = data.notes.contextMeetings.map((item) => `<li>${item}</li>`).join("");

  return `
    <section class="notes-body">
      <div class="notes-toolbar">
        <button class="notes-preset" type="button">Architecture Notes</button>
        <div class="notes-actions">
          <button class="ghost-button" type="button">Regenerate</button>
          <button class="ghost-button" type="button">Copy</button>
        </div>
      </div>
      <h3>Overview</h3>
      <p>${data.notes.summary}</p>
      <h3>Notes</h3>
      <ul class="action-list">${items}</ul>
      <h3>Context</h3>
      <ul class="context-list">${contexts}</ul>
      <h3>Processing</h3>
      <p>${meeting.name} used the ${sentenceCase(data.notes.preset)} preset with ${sentenceCase(data.notes.provider)} ${data.notes.modelName}.</p>
    </section>
  `;
}

function renderRecording(meeting) {
  return `
    <section class="recording-layout">
      <div class="recording-player" aria-label="Recording playback">
        <div class="play-button" aria-hidden="true">Play</div>
        <strong>${meeting.name}</strong>
        <span>${formatDuration(meeting.durationSeconds)} recording preview</span>
      </div>
      <div class="recording-details">
        <h3>Recording</h3>
        <p>Playback sits beside the transcript so a member can jump between audio and spoken text.</p>
        <div class="timeline">
          <span class="timeline-progress"></span>
        </div>
        <div class="recording-meta">
          <span>00:00</span>
          <span>${formatDuration(meeting.durationSeconds)}</span>
        </div>
      </div>
    </section>
  `;
}

function render() {
  renderWorkspaceTree();
  renderWorkspaceCards();
  renderSummary();
  renderMeetings();
  renderMeetingPage();
}

function showHome() {
  state.view = "home";
  render();
}

elements.homeButton.addEventListener("click", showHome);

elements.meetingsButton.addEventListener("click", () => {
  state.view = "meetings";
  state.selectedMeetingId = "";
  state.search = "";
  state.stateFilter = "all";
  elements.searchInput.value = "";
  elements.stateFilter.value = "all";
  render();
});

elements.workspacesButton.addEventListener("click", () => {
  state.workspacesOpen = !state.workspacesOpen;
  renderWorkspaceTree();
  elements.workspacesButton.classList.toggle("is-active", state.workspacesOpen);
});

for (const button of elements.meetingViewBar.querySelectorAll("[data-meeting-mode]")) {
  button.addEventListener("click", () => {
    state.meetingMode = button.dataset.meetingMode;
    renderMeetingPage();
  });
}

elements.searchInput.addEventListener("input", (event) => {
  state.search = event.target.value;
  renderMeetings();
});

elements.stateFilter.addEventListener("change", (event) => {
  state.stateFilter = event.target.value;
  renderMeetings();
});

elements.transcriptSearch.addEventListener("input", (event) => {
  state.transcriptSearch = event.target.value;
  renderTranscript(selectedMeeting());
});

elements.uploadForm.addEventListener("submit", (event) => {
  event.preventDefault();
  const file = elements.recordingFile.files[0];
  const fallbackName = file?.name ? file.name.replace(/\.[^.]+$/, "") : "Uploaded meeting";
  const name = elements.meetingName.value.trim() || fallbackName;

  const meeting = {
    id: crypto.randomUUID(),
    workspaceId: state.workspaceId,
    name,
    recordedAt: new Date().toISOString(),
    state: "queued",
    source: "upload",
    durationSeconds: null,
    accessMode: "workspace",
    preset: elements.presetSelect.value,
  };

  data.meetings.unshift(meeting);
  state.selectedMeetingId = "";
  state.view = "workspace";
  elements.uploadForm.reset();
  elements.presetSelect.value = currentWorkspace().defaultPreset;
  render();
});

elements.presetSelect.value = currentWorkspace().defaultPreset;
render();
