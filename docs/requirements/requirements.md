# System Requirements

Companion to [user-stories.md](user-stories.md) and `rtm.md`. The full product specification is
[Project-Description.md](../../Project-Description.md); this document carries the requirements
derived from it in a form that can be traced and tested.

## Purpose and boundaries

Whadio is an open-source service that records online meetings, transcribes them with speaker
separation, and generates notes from the transcript. It is built for Ukrainian-speaking teams that
meet in Google Meet and whose speech mixes Ukrainian and English — student, research, startup and
IT teams — starting with our own. A Chrome extension records the Meet tab's audio without a bot
joining the call; existing recordings can be uploaded instead. Meetings live in workspaces with
three roles and managed access, subdivided into folders that scope what the model reads when it
writes the notes.

The system runs on ready-made open models, writes notes with a local language model by default,
and processes audio only on its own servers. Anyone can deploy their own instance.

### Out of scope for this version

Recorded with the reason, so that the boundary is a decision rather than an omission.

| Excluded | Why |
|---|---|
| Training or fine-tuning models | Only ready-made open models, including quantized ones, are run. Off-the-shelf models already reach roughly 4% word error rate on Ukrainian; the problem worth solving is code-switching, and the glossary addresses it without training. |
| Bots that join meetings | The Chrome extension captures the tab's audio directly. Meeting platforms increasingly hold unregistered external bots in the lobby or flag them. |
| Native mobile and desktop applications | Android and iOS do not permit an application to capture another application's audio, so a phone application could record the room but not the call. Replaced by one responsive web interface. |
| Publishing the extension to the Chrome Web Store | Review turnaround does not fit the semester. |
| Platforms other than Google Meet | Their recordings can be uploaded as files instead. Direct support only if time remains. |
| Recovering a recording interrupted by a dropped connection or a closed tab | There is no design for it yet, so recording covers the happy path only. To be reconsidered once the extension exists. |
| Real-time transcription | Processing starts after the meeting ends. |
| Languages other than Ukrainian and English; language-switching detection as its own feature | The glossary handles mixed speech without a separate detector. |
| Recognising the same speakers across meetings (voice profiles) | Requires biometric voice data the system deliberately does not hold. |
| Custom roles, and access to individual parts of a transcript | Three fixed roles and per-meeting restriction cover the cases the team identified. |
| Search over the content of transcripts and notes | Requires separate research and a service level agreement due to size and demands, creating a new sub-service. Filtering by name and date is in scope. |
| Note formats written by users as their own prompts | Opens the system to prompt injection. Fixed presets only. |
| Editing the notes a model produced | Regenerating them with a different preset covers the case that motivated it. Editing the transcript stays in scope, because only the transcript is a record of what was said. |
| Excluding an individual meeting from serving as context | Cut when the story set was consolidated. A meeting is kept out of the context set by restricting its access or by moving it to another folder. |
| Meetings from another folder, or another workspace, as context | Context is scoped to the folder a meeting sits in. Explicit cross-folder inclusion was considered and cut; the workspace boundary is never crossed at all. |
| Moving a meeting between workspaces | Who owns the recording afterwards, whether the source workspace's glossary still governs an already-produced transcript, and how the capacity limit accounts for the move are all undecided, and it opens the only authorization path that crosses the access boundary. Moving between folders is in scope. |
| Redaction of names spoken inside the transcript body | Requires named-entity recognition for Ukrainian. Speaker labels are redacted instead, which falls out of speaker separation at no extra cost. |
| Reading transcripts aloud, colour-blind modes and similar accessibility work | Cannot be committed to this semester. The original recording already covers the audio case. |
| An uptime guarantee | The service runs on a single host, and redundancy isn't in the budget. |
| An owner-controlled switch for whether recordings are stored at all | Cut when the story set was consolidated. The retention policy already deletes recordings three months after the meeting; a workspace-level override would add a second deletion path to specify and verify. |
| Sending a user's records out by email | Meeting content would leave the system, which the privacy requirement forbids. Users are warned before deletion and export themselves. |
| Video capture | Audio only. |
| Payments, pricing plans and paid tiers | The service is free and open-source. |
| Transfer of workspace ownership | The confirmation mechanism was never specified and no user has asked for it. The consequence is accepted: a workspace whose Owner leaves is stranded — its meetings stay reachable to its members, but the provider key, the ownership and the deletion cannot be changed. |
| Tags on meetings, and filtering by tag | Their value only appears at a volume this version will not reach. Filtering by name and date covers the same need over a list of tens of meetings. |
| Per-share permission sets, and shares addressed to an email address | A share grants reading only. Per-share permissions would make authorization the union of workspace role, per-meeting restriction and share grant on every path that returns content, and every one of those paths would then have to be verified against all three. Email-addressed shares need an invitation flow for accounts that may not exist, duplicating the workspace invitation. |
| A capacity display in the interface | The limit, the eviction and the notice naming the evicted meeting are stated and verified as a non-functional requirement. A separate screen adds no behaviour that this verification does not already exercise. |

## Glossary

| Term | Definition |
|---|---|
| **Workspace** | The access boundary. Carries the membership list and the three workspace roles. Every User receives a personal workspace on registration; organisational workspaces are created by their Owner. Nothing crosses this boundary except a share: meetings do not move between workspaces, and are never used as context outside their own. |
| **Folder** | The context boundary inside a workspace, and its only organisational subdivision. Carries no permissions of its own and cannot be nested. Every workspace has one default folder. |
| **Meeting** | One record: its recording, its transcript and its notes. Moved, shared and deleted as a unit. |
| **Recording** | The captured audio of a meeting. Deleted three months after the meeting under the retention policy. |
| **Transcript** | The text of a meeting, split into timestamped segments attributed to speakers. |
| **Notes** | The text generated from a transcript by a language model, using a preset. A layer above the transcript, never a replacement for it. |
| **Preset** | A named note format — a summary with action items, a detailed write-up, an interview. Each preset is a fixed prompt; users do not write their own. |
| **Context set** | The transcripts supplied to the model alongside a meeting's own when its notes are generated: the other meetings in the same folder, minus any whose access is restricted. |
| **Glossary (project)** | The workspace's list of terms and names supplied to the recognition step to improve accuracy on the workspace's own vocabulary. Distinct from this section. |
| **Share** | A grant of read access to one meeting for a signed-in person outside the workspace, created as a link and revocable. Opening the link only requests access; the share is bound to the one account its creator approves. A share carries no download, export or onward-share right. |
| **Diarization** | Splitting a transcript by who spoke when. Produces numbered speakers before any names are attached. |
| **BYOK** | Bring Your Own Key — a workspace Owner connecting their own LLM provider API key in place of the built-in model. |
| **MCP** | Model Context Protocol — the integration through which a user's own AI assistant reaches the meetings they have access to. |
| **VTT** | WebVTT, the subtitle format used for transcript export; carries cue times and speaker attribution. |
| **WER** | Word error rate — the share of words a recognition system gets wrong, used to compare model configurations. |
| **Open core** | Shipping an unrestricted open-source build while the instance the team hosts carries usage limits. The pattern behind the per-workspace meeting limit. |

### Roles

System level:

- **User** — a registered account: creates workspaces, records and uploads meetings, creates access keys for their own AI assistant.
- **Administrator** — monitors system operation. Sees operational metadata only, with no access to recordings, transcripts or notes.

Workspace level — exactly three roles; each has all the permissions of the previous one:

- **Member** — records and uploads meetings; views, corrects, exports and shares the meetings accessible to them; organises them into folders; adds to the glossary.
- **Moderator** — additionally restricts access to individual meetings, and manages the workspace's members.
- **Owner** — additionally configures the LLM provider and deletes the workspace.

Folders carry no permissions: access is decided by the workspace role and by per-meeting
restriction, never by where a meeting is filed.

## Functional requirements (FR)

### Accounts and access

- FR-001: Registration from an email address and a password creates an account and a personal workspace with that account as its Owner.
- FR-002: Registration requires accepting the Terms and Conditions, which state the obligation to obtain the participants' consent before recording and the restrictions on sharing. Without acceptance no account is created.
- FR-003: Sign-in with correct credentials grants access to the workspaces the account belongs to; incorrect credentials are denied and create no session.
- FR-004: Every path that returns meeting content requires a signed-in account. An unauthenticated request yields a sign-in prompt and none of the content.
- FR-005: A User can create a workspace with a name, which is created with them as its Owner, holding one default folder and no meetings. A workspace submitted without a name is rejected.
- FR-006: A Moderator can invite a person to the workspace as a Member or a Moderator; the Owner role cannot be assigned by invitation. The invited person accepts or declines, and on acceptance joins with the chosen role.
- FR-007: A Moderator can remove a member, and change a member's role between Member and Moderator with effect from that member's next action. The Owner can be neither removed nor re-roled, and Members have no member-management actions.
- FR-008: An Owner can delete a workspace together with its folders, meetings, recordings, transcripts and notes. No other role can delete a workspace, and a personal workspace cannot be deleted at all.

### Capture

- FR-009: On a Google Meet call the extension offers to record and reminds the user to obtain the participants' consent. Recording does not start until the user confirms that consent was obtained, and the confirmation is stored with the meeting.
- FR-010: The extension captures the Meet tab's audio together with the user's microphone into a single recording, without joining the call as a participant. While recording it reports that recording is active and how long it has run; on stop the captured audio is complete and playable.
- FR-011: Recording is offered only where the browser supports tab audio capture. Where it does not, the reason is stated and file upload is offered instead.
- FR-012: A finished recording is delivered to a chosen workspace and folder as a meeting queued for processing, through the same ingest path as an uploaded file. Where no destination was chosen, the meeting is created in the member's personal workspace's default folder.
- FR-013: A Member can upload an existing audio recording to a workspace. A file that is not a supported audio recording is rejected with an error and creates no meeting.
- FR-014: The system reports each meeting's processing state — queued, processing, processed or failed — wherever the meeting is listed.
- FR-015: The system transcribes a recording and splits the transcript by speaker.
- FR-016: Speakers in extension recordings are labelled from the Google Meet participant list. For uploaded files, and wherever that list cannot be read, speakers are labelled Speaker 1, Speaker 2 and so on, and the meeting is marked as having unnamed speakers.
- FR-017: A Member can rename a speaker; the new label applies to every segment attributed to that speaker.

### Notes

- FR-018: Notes are generated from the transcript using a preset chosen from a fixed set, and contain the sections that preset defines. Where no preset is chosen the workspace's default preset is used. The prompt behind a preset is neither shown nor editable.
- FR-019: The context set for a meeting's notes is the other meetings in its folder, minus meetings whose access is restricted. Meetings in other folders and in other workspaces are never part of it, and a folder holding a single meeting produces notes with no context supplied.
- FR-020: The meetings used as context are recorded with the generated notes and shown to anyone who opens them.
- FR-021: An Owner can configure an LLM provider and API key for the workspace; the configuration is available to no other role. Where a provider is configured, the workspace states that the transcripts in the context set are sent to it.
- FR-022: Without a provider configured, notes are generated by the built-in local model and no request leaves the system.
- FR-023: Where a configured provider fails, the meeting is shown as failed with the cause, and generation with the built-in model is offered.
- FR-024: The member is notified when a meeting finishes processing and when its processing has finally failed. The notification carries a link to the meeting and none of its content.
- FR-025: Notes can be regenerated with a different preset up to a configured number of times per meeting; beyond that limit the system refuses and states it. The transcript is never regenerated.
- FR-026: The notes a regeneration replaces remain reachable, and a failed run leaves the previous notes as the current ones.

### Transcript

- FR-027: The transcript is displayed as timestamped segments attributed to speakers, with playback from any segment while the recording is stored. After the recording is deleted the transcript and notes remain and playback is unavailable.
- FR-028: A Member can edit a transcript's text. Any change a member makes to a transcript — its text or its speaker labels — retains the original unchanged, marks the meeting as edited, and keeps both versions reachable wherever the meeting is viewed, exported or shared.
- FR-029: A workspace holds a glossary of terms, supplied to the recognition step when that workspace's meetings are transcribed. A removed term is no longer supplied to later transcriptions, and a term already present is rejected as a duplicate.
- FR-030: A term corrected in a transcript can be added to the workspace glossary, recorded with the meeting it came from.

### Organisation

- FR-031: A workspace lists the meetings accessible to the member, each with its name, its date and time, and its processing state; a workspace holding none states so. The list extends as the member scrolls, without reloading the page.
- FR-032: Meetings can be filtered by name and by date range. A filter that matches nothing states so.
- FR-033: After processing, the member is prompted to name the meeting; where no name is given the system applies one generated from the transcript. The name is editable at any time, and the meeting's date and time are stored separately from it and are not editable.
- FR-034: A workspace can hold folders, which cannot be nested. A meeting created without a folder is placed in the workspace's default folder, and deleting a folder moves its meetings to the default folder without deleting any of them.
- FR-035: A meeting can be moved to another folder in its workspace, carrying its recording, transcript and notes; only folders in the same workspace are offered. Existing notes are unchanged by the move, and the destination folder governs the context set of the next generation.
- FR-036: A meeting can be deleted with its recording, transcript and notes by the member who recorded it or by a Moderator, on confirmation. No other member is offered the action, and notes elsewhere that used the meeting as context are unchanged.

### Sharing

- FR-037: A Moderator can restrict a meeting to selected workspace members. A restricted meeting is withheld from every other member on every path that returns meeting content — the meeting list, direct links, a connected assistant, and the context set of other meetings' notes. Members are not offered the action.
- FR-038: A Member can share a meeting outside the workspace by link. The recipient must be signed in and may read the transcript and notes only, with no download, export or onward share. Access is granted only after the Member who created the share approves the requesting account; the share is then bound to that account, and any other account opening the link sees none of the content. The creator is notified of each request; the notification names the requesting account and carries none of the meeting's content. A share can be revoked, after which the link denies access.
- FR-039: A share can redact speaker names to Speaker 1, Speaker 2 and so on. A redacted share carries no recording.

### Export and operations

- FR-040: A meeting's transcript and notes can be exported for download as Markdown, and the transcript also as VTT; the transcript export is split by speaker labels, and the notes export is offered only once notes exist. Timestamps are optional in the Markdown transcript export, and always present in VTT, which is a timed format.
- FR-041: An export carries the current state of the content, corrections and edits included, and states where the transcript was edited.
- FR-042: Every export opens with a notice that the content must not be shared without the participants' permission, and ends with a line attributing it to Whadio.
- FR-043: A User can create and revoke personal keys for the MCP server, through which an AI assistant reaches the system. A key is shown once and stored only in hashed form, and a revoked key is rejected.
- FR-044: An assistant using a key reaches only the meetings the key's owner has access to; a restricted meeting they were not selected for is not returned.
- FR-045: The administrator dashboard reports the processing queue with each job's workspace, state and waiting time, failures with their causes, server load, and built-in model usage against its limits. No dashboard view exposes recording, transcript or notes content.

### Retention

- FR-046: Recordings are deleted three months after the meeting, with the members who have access warned in advance. The transcript and the notes survive the deletion.

## Non-functional requirements (NFR)

### Performance efficiency

* NFR-001 (Time behaviour): Pages containing a user's workspaces, folders and meetings load in under 2 seconds for at least 90% of requests.

* NFR-002 (Time behaviour): For a recording of up to one hour, the system generates the transcript within 15 minutes in at least 90% of processing runs.

* NFR-003 (Capacity): The hosted service supports up to 1000 meetings per user. When a new meeting would exceed this limit, the oldest meeting is deleted.

### Compatibility

* NFR-004 (Co-existence): While recording a Google Meet call, the extension captures the meeting audio without affecting the operation of the meeting or the functionality of the browser environment in which the call is running.

### Usability

* NFR-005 (User error protection): An accidental user action that changes a meeting's project or folder, or applies an incorrect note preset, can be reversed without losing the meeting, its transcript or its previously generated notes.

* NFR-006 (User error protection): When a transcript has been edited, the system clearly indicates that it differs from the original and allows the user to switch between the original and edited versions.

### Security

* NFR-007 (Confidentiality): Meeting recordings, transcripts and notes are accessible only to authenticated users who have permission to access the corresponding meeting.

* NFR-008 (Confidentiality): A user who receives access to a shared meeting cannot forward, copy or download its content unless the sharing permissions explicitly allow the corresponding action.

* NFR-009 (Confidentiality): The system does not expose a meeting's recording, transcript or notes to users outside the access rules defined for the meeting, including through direct links, exports or connected services.

* NFR-010 (Accountability): Every change to a meeting that can affect its content or access is associated with the account that performed the action, without exposing unnecessary personal information in the record.

* NFR-011 (Integrity): An edited transcript is never presented as the original transcript; whenever an edited version is displayed or exported, the system indicates that the transcript has been edited.

* NFR-012 (Authenticity): User accounts are authenticated by their registered credentials, and a user cannot access another user's account by impersonating that user.

* NFR-013 (Confidentiality): API keys configured for an external LLM provider are available only to the workspace Owner and are not exposed to other workspace members.

### Reliability

* NFR-014 (Recoverability): If a processing component of the system becomes unavailable, meetings already received by the system remain stored and available for download or later processing.

* NFR-015 (Fault tolerance): A failure of the transcription or note-generation component does not make the entire Whadio service unavailable; functionality unrelated to the failed component remains accessible.

### Portability

* NFR-016 (Adaptability): The open-source version of Whadio can be deployed in an environment that satisfies the documented CPU, RAM, disk-space and, where required, GPU requirements.

* NFR-017 (Installability): Deployment requirements and resource requirements for running Whadio are documented so that the system can be installed and operated outside the team's hosted environment.

## AI Usage

This document was prepared with the assistance of Claude Code (Claude Opus 5). The requirements
derive from the mini technical specification agreed in Lab 1 and from the team's working session of
2026-09-19. The authors reviewed and edited the content, and the document is reviewed through a
pull request before merging.
