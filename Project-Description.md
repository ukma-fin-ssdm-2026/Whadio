# Whadio — project description

Team `sztorm@localhost:3000`

## Project idea

Whadio is an open-source service for recording and transcribing online meetings that bets on high-quality recognition of Ukrainian, including mixed Ukrainian–English speech. The user records a Google Meet meeting right in the browser, without a bot in the call, and after it ends receives a speaker-labeled transcript and notes. Meetings are organized into workspaces with roles, a shared glossary of terms, and managed access; results can be exported to Markdown or connected to your own AI assistant via MCP.

Whadio is meant to be inexpensive and private. Inexpensive, because it runs on ready-made open models, and notes are written by a local language model by default; if desired, you can connect your own API key for a commercial model (BYOK). Private, because the code is open and anyone can deploy their own instance, while on the shared site audio does not leave Whadio's servers, and Whadio does not use data to train models. The first direction is NaUKMA student teams, starting with our own.

## Mini technical specification

### 1. System purpose

Existing meeting transcription services often make mistakes on Ukrainian speech containing English terms and names, charge per user, store recordings in their own clouds, or add a bot to the call. Whadio solves these problems for Ukrainian-speaking teams that regularly meet in Google Meet (student, research, startup, and IT teams): it records the meeting from the browser, recognizes it with open models taking the workspace glossary into account, splits it by speaker, generates notes, and stores everything in a workspace with controlled access.

### 2. System boundaries

**In scope for the semester:** the functions from item 4 — recording Google Meet via a Chrome extension and uploading existing recordings, transcription with speaker separation, the glossary, notes from presets with cross-meeting context, workspaces with roles and folders, editing with the original preserved, sharing outside the workspace, Markdown and VTT export, MCP, retention, monitoring.

**Out of scope:**

- training and fine-tuning models — only running ready-made (including quantized) models;
- bots that join meetings;
- desktop and mobile apps (web app and Chrome extension only); publishing the extension to the Chrome Web Store;
- platforms other than Google Meet — only if time remains and there are no other tasks (their recordings can be uploaded as files);
- real-time transcription: processing starts after the meeting ends;
- languages other than Ukrainian and English; language-switching detection as a separate feature;
- recognizing the same speakers across meetings (voice profiles);
- custom roles and access to individual parts of a transcript;
- note formats defined by users' own prompts — only fixed presets;
- search over the content of transcripts and notes — filtering by name and date is in scope; tags on meetings and filtering by tag;
- per-share permission sets — a share grants reading only — and shares addressed to an email address; redaction of names spoken inside the transcript body — only speaker labels are redacted;
- transfer of workspace ownership; moving a meeting between workspaces, and using as context a meeting from another workspace or another folder; excluding an individual meeting from serving as context;
- recovering a recording interrupted by a dropped connection or a closed tab — recording covers the happy path only; editing the notes a model produced — regenerating them with a different preset covers that case; an owner-controlled switch for whether recordings are stored at all;
- an uptime guarantee — the service runs on a single host;
- video;
- payments and pricing plans.

### 3. User roles

System level:

- **User** — a registered account: creates workspaces, records and uploads meetings, creates MCP access keys. For personal meetings, has a personal workspace where they are the Owner.
- **Administrator** — monitors system operation: the processing queue and failures, server load, usage limits for built-in models. Sees only operational metadata, with no access to recordings, transcripts, or notes.

Workspace level — exactly three roles; each subsequent role has all the permissions of the previous one. A meeting belongs to a workspace and is accessible to all of its members by default.

- **Member** — records and uploads meetings; views, corrects, exports, and shares the meetings accessible to them; organizes them into folders; adds to the glossary.
- **Moderator** — restricts access to individual meetings to a circle of selected members, and manages the workspace's members: invites them, removes them, and changes their roles between Member and Moderator.
- **Owner** — connects their own LLM provider API key to the workspace, deletes the workspace.

Folders carry no permissions of their own: access is decided by the workspace role and by per-meeting restriction, never by where a meeting is filed.

### 4. Key functions

1. **Recording and transcription** — a Chrome extension records the Google Meet tab audio and the microphone, or the user uploads an existing recording; before recording starts, the extension reminds the user about consent and requires them to confirm they have it. After the meeting ends, a transcript appears, and the user is notified when it is ready.
2. **Speakers** — the transcript is split by speaker; in recordings from the extension, speakers are automatically labeled with the names of the call participants from Google Meet; labels can be corrected.
3. **Workspace glossary** — terms and names that improve recognition accuracy in the workspace's meetings; a term corrected in a transcript can be added to the glossary.
4. **Notes** — notes from the transcript using a chosen preset (summary with action items, detailed write-up, interview), generated by the built-in local model or by a provider's model with your own key. Presets are fixed; users do not write their own prompts. Notes can be regenerated a limited number of times; the transcript itself is never regenerated.
5. **Cross-meeting context** — when a meeting's notes are generated, the transcripts of the other meetings in the same folder are supplied to the model, so that recurring topics and action items carry forward. A meeting under access restriction is never used as context for another meeting.
6. **Workspaces, folders and access** — creating workspaces, invitations, assigning roles, restricting access to individual meetings; folders inside a workspace, moving a meeting between folders with its recording, transcript, and notes; meeting names proposed by the model after the meeting and editable afterwards, with date and time kept as metadata outside the name; filtering by name and date.
7. **Editing and provenance** — transcripts can be edited; the original is always retained, the record is marked as edited, and both versions can be viewed. The system never presents an edited transcript as the original.
8. **Sharing** — a meeting can be shared outside the workspace by link, granting reading of the transcript and notes and nothing else; recipients must be signed in, and can neither download nor pass the meeting on. A share can be revoked, and can additionally redact the speakers' names, in which case it carries no recording.
9. **Export and AI integrations** — exporting transcripts and notes to Markdown and transcripts to VTT, with attribution and a consent notice carried in the file; an MCP server with personal keys that gives the AI assistant only the meetings accessible to the user.
10. **Retention** — recordings are deleted three months after the meeting, with a warning beforehand; transcripts and notes survive the deletion.
11. **Monitoring** — an administrator dashboard: processing queue status, failures and their causes, server load, built-in model usage.

### 5. Non-functional requirements

1. **Privacy.** Audio is processed only by Whadio's servers; meeting text leaves the system only to an LLM provider explicitly connected by the workspace owner, or to the user's MCP client; Whadio does not use data to train models. Verification: with default settings, full processing of a meeting runs in a network-isolated environment without a single external request.
2. **Access control.** Recordings, transcripts, and notes are accessible only to workspace members with access to the corresponding meeting, including via MCP; the administrator receives only metadata. Verification: automated authorization tests cover 100% of the endpoints that return meeting content.
3. **Performance.** For a recording up to 60 min long, the transcript and the notes from the built-in model become available no later than 20 min after the recording stops (for files — after the upload completes) in 95% of cases, with up to 3 recordings processed concurrently on the reference GPU server.
4. **Recognition accuracy.** On a frozen evaluation set (≥ 30 min of Ukrainian and mixed Ukrainian–English speech with manually verified transcripts), the word error rate (WER) of every model configuration used in deployment exceeds the WER of the full-precision model, measured when the set was frozen, by no more than 2 percentage points.

### 6. Assumptions and constraints

- **Stack:** Python (FastAPI) for the backend and ML processing (PyTorch / ONNX Runtime), React for the frontend, a Chrome extension (Manifest V3), PostgreSQL; audio in file-based or S3-compatible storage; local environment — Docker Compose.
- **Models:** only ready-made open models with licenses compatible with open source: speech recognition (for example, NVIDIA Parakeet, Whisper), speaker separation (pyannote), local LLM (for example, Gemma, Qwen). The pyannote weights on Hugging Face are available after accepting the terms of use.
- **Hardware and deployment:** two profiles — full precision on GPU (the reference server is a team member's computer) and quantized on CPU (development on any laptop and a fallback for the demo). Initially the system runs locally; deployment on AWS is possible, but the decision has not been made yet.
- **Browsers:** recording — only in desktop Chrome on Windows, macOS, and Linux (the extension and tab audio capture are available only in Chromium-based browsers); viewing and management — in any modern browser.
- **External services:** Google Meet — without an official API: the extension reads speaker names from the Meet interface, which may change (in that case, manual labeling remains); LLM providers for users' own keys (Anthropic, OpenAI, Google); users' MCP clients.
- **Existing work:** the starting point is Andrii's ML pipeline (recognition, speaker separation, notes); we record its transfer into the repository with a reference to the source.
- **Data and consent:** the evaluation set consists of recordings of our team's meetings, made with the consent of everyone present, which are not shared with external services; free API keys are used only for data without personal information, because free tiers may use input data for training. The person recording informs the other participants about the recording and confirms this before recording starts.
- **Unverified assumption:** we verify the recognition quality of mixed speech with an early prototype on the evaluation set; we record the result and, if needed, adjust the technical specification.
- **Team time:** 4 people at 5–6 h/week each (≈ 22 h/week in total) over 11 weeks, alongside other course assignments.

## AI usage

The document was prepared with the help of Claude Code (Claude Opus 5 model) based on the team's decisions; the content was manually checked and edited, and the document is reviewed via a pull request before merging.
