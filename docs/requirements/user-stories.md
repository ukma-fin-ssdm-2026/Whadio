# User Stories

Format: As a <role>, I want <capability>, so that <benefit>.

Each story has acceptance criteria in Given/When/Then form.

## Stories

### Accounts and access

- US-001: As a visitor, I want to register and sign in, so that my Meetings are tied to my own account and nobody can act as me.
  - Acceptance criteria:
    - [ ] Given a visitor with no account on an instance in `verified` mode, when they register with an email address, then a single-use link is sent to that address and no account exists yet.
    - [ ] Given a visitor opens their registration link within 24 hours, when they enter a name, set a password and accept the Terms and Conditions, then an account is created and a personal Workspace is created with them as its Owner.
    - [ ] Given a registration link was already used or is older than 24 hours, when it is opened, then no account is created.
    - [ ] Given a registration link was sent to an address less than 20 minutes ago, when someone registers with that address again, then no email is sent and the earlier link keeps working.
    - [ ] Given an address already has an account, when someone registers with it, then they see the same response as for a new address, and the email sent there points to sign-in and carries a password-reset link.
    - [ ] Given a visitor is registering, when they submit the form without accepting the Terms and Conditions, then registration is refused and no account is created.
    - [ ] Given an instance runs in `invite-only` mode, when a visitor looks for registration, then none is offered.
    - [ ] Given an instance in either mode, when the operator issues a registration link for an address from the command line, then the link is shown to the operator, and opening it creates the account as an emailed link does.
    - [ ] Given a registered User, when they sign in with correct credentials, then they gain access to the Workspaces they belong to.
    - [ ] Given a registered User, when they sign in with an incorrect password, then access is denied and no session is created.
    - [ ] Given a visitor is not signed in, when they open a Meeting's URL, then they are asked to sign in and none of the Meeting's content is shown.

- US-002: As a User, I want to create a Workspace and control who belongs to it and what they may do, so that a team's Meetings live together under access I manage.
  - Acceptance criteria:
    - [ ] Given a signed-in User, when they create a Workspace with a name, then the Workspace is created with them as its Owner, holding a default Folder and no Meetings.
    - [ ] Given a User submits a Workspace without a name, when they confirm, then the System rejects it with a validation error and no Workspace is created.
    - [ ] Given a Moderator is in their Workspace, when they invite a person by email address and choose their role, then a single-use invitation link is created, sent to that address in `verified` mode or shown to the Moderator to hand over in `invite-only` mode, and Owner is not among the roles they could assign.
    - [ ] Given a person has received an invitation, when they accept it, then they join the Workspace with the chosen role and see the Meetings accessible to them.
    - [ ] Given a person without an account opens an invitation link, when they enter a name, set a password and accept the Terms and Conditions, then an account with the invited address and its personal Workspace are created, and the account joins the Workspace with the chosen role.
    - [ ] Given a person without an account opens an invitation link, when they submit the form without accepting the Terms and Conditions, then no account is created and nobody joins the Workspace.
    - [ ] Given an account whose email address differs from the invited one opens an invitation link, when it tries to accept, then it is refused and does not join.
    - [ ] Given an invitation link was already used or is older than 7 days, when it is opened, then it is refused.
    - [ ] Given an address has a pending or expired invitation to the Workspace, outside the one-day wait of `verified` mode, when a Moderator invites it again, then the earlier link stops working and a new one is created.
    - [ ] Given an instance in `verified` mode and an address invited to the Workspace less than a day ago, when a Moderator invites it again, then the invitation is refused and the earlier link keeps working.
    - [ ] Given a User has invited 20 addresses in the past day, when they invite another, then it is refused.
    - [ ] Given a Moderator opens the Workspace's pending invitations, when they cancel one, then its link is refused.
    - [ ] Given the Moderator who created an invitation was removed or made a Member, when its link is opened, then it is refused.
    - [ ] Given a person has received an invitation, when they decline it, then they do not join the Workspace.
    - [ ] Given a Moderator opens the member list, when they remove a member, then that member loses access to the Workspace and all of its Meetings.
    - [ ] Given a Moderator opens the member list, when they change a member's role between Member and Moderator, then the new role's permissions apply on that member's next action.
    - [ ] Given a Moderator opens the member list, when they view the Owner's entry, then they can neither remove the Owner nor change the Owner's role.
    - [ ] Given a Member opens the Workspace, when they view the member list, then no member-management actions are available to them.
    - [ ] Given an Owner opens the Workspace settings, when they delete the Workspace and confirm, then the Workspace, its Folders, Meetings, recordings, transcripts and notes are removed.
    - [ ] Given a Moderator opens the Workspace settings, when they look for a delete action, then none is available.
    - [ ] Given a User opens their personal Workspace's settings, when they look for a delete action, then none is available.

- US-020: As a User, I want to reset a forgotten password through my email address, so that I do not lose my account and its Meetings.
  - Acceptance criteria:
    - [ ] Given an instance in `verified` mode, when a User requests a password reset for their email address, then a single-use link valid for 1 hour is sent to that address.
    - [ ] Given the User opens the reset link in time, when they set a new password, then they can sign in with it and every earlier session and extension token of the account is ended.
    - [ ] Given a reset link was already used or is older than 1 hour, when it is opened, then the password stays unchanged.
    - [ ] Given a reset link was sent to an address less than 20 minutes ago, when another reset is requested for it, then no email is sent and the earlier link keeps working.
    - [ ] Given an address has no account, when someone requests a reset for it, then they see the same response as for an existing address and no email is sent.
    - [ ] Given an instance runs in `invite-only` mode, when a User looks for a password reset, then none is offered.
    - [ ] Given an instance in either mode, when the operator issues a reset link for an account from the command line, then the link is shown to the operator, and opening it sets a new password as an emailed link does.

### Capture

- US-003: As a Member, I want to record an online meeting from my browser and have it arrive in a Workspace ready for processing, so that the meeting is captured without a bot in the call and without me handling files.
  - Acceptance criteria:
    - [ ] Given the Member has the extension installed, when they join a Google Meet call, then the extension displays a prompt offering to record together with a reminder to obtain the participants' consent.
    - [ ] Given the Member has not confirmed that consent was obtained, when they try to start recording, then recording does not start.
    - [ ] Given the Member confirms that consent was obtained, when they start recording, then the tab's audio and their microphone are captured into one recording, no additional participant appears in the call, and the confirmation is stored against the Meeting.
    - [ ] Given a recording is in progress, when the Member opens the extension, then it shows that recording is active and how long it has been running.
    - [ ] Given a Member stops the recording, when it ends, then the captured audio is complete and playable.
    - [ ] Given a recording has finished, when the Member confirms the destination, then a Meeting is created in that Workspace and Folder and queued for processing.
    - [ ] Given the Member chose no destination, when the recording finishes, then the Meeting is created in their personal Workspace's default Folder.
    - [ ] Given a Meeting has been queued, when the Member opens the Workspace, then the Meeting is listed as being processed.
    - [ ] Given the Member's browser is not Chromium-based, or is a phone browser, when they open Whadio or the extension, then recording is not offered, the reason is stated, and file upload is offered instead.

- US-004: As a Member, I want to upload a recording I already have, so that I can obtain the transcript and notes even from platforms which the System doesn't support.
  - Acceptance criteria:
    - [ ] Given the Member has logged in, when they open one of their Workspaces, then they can upload a meeting recording to it.
    - [ ] Given the Member has uploaded a meeting recording, when the upload finishes, then the System starts processing it and shows the Meeting in the Workspace as being processed.
    - [ ] Given the Member selects a file that is not a supported audio recording, when they try to upload it, then the System rejects it with an error message and no Meeting is created.
    - [ ] Given an uploaded recording is being processed, when the processing fails, then the Meeting is shown in the Workspace as failed to process.

- US-005: As a Member, I want the transcript split by speaker with the right names on it, so that I can tell who said what without identifying voices by hand.
  - Acceptance criteria:
    - [ ] Given a Meeting was recorded through the extension, when its transcript is produced, then each speaker's segments carry a name taken from the Google Meet participant list.
    - [ ] Given a Meeting was uploaded as a file, when its transcript is produced, then speakers are labelled Speaker 1, Speaker 2 and so on.
    - [ ] Given the extension could not read the participant list, when the transcript is produced, then speakers are labelled Speaker 1, Speaker 2 and so on, and the Meeting is marked as having unnamed speakers.
    - [ ] Given a Member views a transcript, when they rename a speaker, then every segment attributed to that speaker shows the new label.
    - [ ] Given a speaker label has been corrected, when the transcript is exported, then the export carries the corrected label.
    - [ ] Given a Member has renamed a speaker, when any Member opens the Meeting, then it is marked as edited and the original labels remain retrievable.

### Notes

- US-006: As a Member, I want notes generated from the transcript in a format that matches the kind of meeting it was, so that I get the write-up I need without reading the whole transcript.
  - Acceptance criteria:
    - [ ] Given a Member opens a processed Meeting, when they generate its notes, then they can choose from the available presets.
    - [ ] Given a preset has been chosen, when the notes are generated, then the notes contain the sections that preset defines.
    - [ ] Given no preset is chosen, when the notes are generated, then the Workspace's default preset is used.
    - [ ] Given a Member opens the preset list, when they view a preset, then there is no option to enter or edit the prompt behind it.

- US-007: As a Member, I want a Meeting's notes to draw on the other Meetings in the same Folder, so that recurring topics and action items are carried forward.
  - Acceptance criteria:
    - [ ] Given a Meeting sits in a Folder with other Meetings, when its notes are generated, then the transcripts of those other Meetings are supplied to the model as its context set.
    - [ ] Given a Meeting's notes were generated with a context set, when a Member opens the notes, then the Meetings used as context are listed.
    - [ ] Given a Meeting in the Folder is under access restriction, when notes are generated for another Meeting in that Folder, then the restricted Meeting is not part of the context set.
    - [ ] Given a Folder holds only one Meeting, when its notes are generated, then no other transcript is supplied and the notes are still produced.

- US-008: As an Owner, I want to connect my Workspace to my own model provider, so that I can trade higher note quality against keeping the content inside the System.
  - Acceptance criteria:
    - [ ] Given no provider key is configured for the Workspace, when a Meeting's notes are generated, then the built-in local model is used and no request leaves the System.
    - [ ] Given the Owner opens the Workspace settings, when they enter a provider API key and select a model, then the Workspace uses that provider for note generation.
    - [ ] Given a Moderator or a Member opens the Workspace settings, when they look for the provider configuration, then none is available to them.
    - [ ] Given a provider key is configured, when a request to the provider fails, then the Meeting is shown as failed with the cause and the Member is offered generation with the built-in model.
    - [ ] Given a provider key is configured, when notes are generated, then the Workspace states that the transcripts in the context set are sent to that provider.

- US-009: As a Member, I want to be notified when a Meeting has finished processing, so that I don't have to check back every few minutes.
  - Acceptance criteria:
    - [ ] Given a Member started processing a Meeting, when the processing completes, then the Member is notified that the transcript and notes are ready.
    - [ ] Given the Member is notified, when they open the notification, then it carries a link to the Meeting and none of its transcript or notes content.
    - [ ] Given the processing of a Meeting fails, when the failure is final, then the Member is notified that the Meeting failed to process.

- US-010: As a Member, I want to regenerate a Meeting's notes with a different preset, so that choosing the wrong one doesn't cost me the meeting.
  - Acceptance criteria:
    - [ ] Given a Meeting already has notes, when a Member regenerates them with a different preset, then the new notes are shown and the transcript is unchanged.
    - [ ] Given a Meeting's notes have been regenerated, when a Member looks for the notes they replaced, then those remain reachable.
    - [ ] Given a Meeting's notes have been generated the permitted number of times, when a Member tries to regenerate them again, then the System refuses and states the limit.
    - [ ] Given notes are being regenerated, when the run fails, then the previous notes remain the current ones.

### Transcript

- US-011: As a Member, I want to read the transcript alongside the recording and correct what was misheard, with the original always kept, so that the record is accurate and nothing can be passed off as verbatim.
  - Acceptance criteria:
    - [ ] Given a Member opens a processed Meeting, when they view the transcript, then it is shown as segments, each carrying a timestamp and a speaker label.
    - [ ] Given the Meeting's recording is still stored, when the Member selects a transcript segment, then the recording plays from that point.
    - [ ] Given the recording has been deleted under the retention policy, when the Member opens the Meeting, then the transcript and notes are still shown and playback is unavailable.
    - [ ] Given a Member edits a Meeting's transcript, when they save, then the edited version is displayed and the original is retained unchanged.
    - [ ] Given a Meeting's transcript has been edited, when any Member opens the Meeting, then it is marked as edited.
    - [ ] Given a Meeting is marked as edited, when a Member chooses to view the original, then the original is displayed and they can switch back to the edited version.
    - [ ] Given an edited Meeting is exported or shared, when the recipient opens it, then it states that the transcript was edited.

- US-012: As a Member, I want the Workspace to hold the terms and names we use, so that they are recognised correctly in our meetings instead of being misheard every time.
  - Acceptance criteria:
    - [ ] Given a Member opens the Workspace glossary, when they add a term, then it is stored for that Workspace.
    - [ ] Given the Workspace glossary holds terms, when a new Meeting in that Workspace is transcribed, then those terms are supplied to the recognition step as biasing input.
    - [ ] Given a Member removes a term, when a new Meeting is transcribed, then that term is no longer supplied.
    - [ ] Given a term already exists in the Workspace glossary, when a Member adds it again, then it is rejected as a duplicate.
    - [ ] Given a Member has corrected a word in a transcript, when they choose to add it to the glossary, then the corrected form is stored and listed together with the Meeting it came from.

### Organisation

- US-013: As a Member, I want to browse, name and filter the Workspace's Meetings, so that I can return to what was discussed without scrolling through the list.
  - Acceptance criteria:
    - [ ] Given a Workspace holds no Meetings, when a Member opens it, then they see a message that there are no Meetings yet.
    - [ ] Given a Workspace holds Meetings, when a Member opens it, then they see the Meetings accessible to them, each with its name, its date and time, and its processing state.
    - [ ] Given a Member is viewing the Meeting list, when they open one of the Meetings, then the System shows its transcript and notes.
    - [ ] Given a Member is viewing a long list of Meetings, when they scroll down, then further Meetings are loaded without reloading the page.
    - [ ] Given a Workspace holds Meetings, when a Member filters by a date range, then only Meetings recorded within that range are listed.
    - [ ] Given a Member filters by name, when the filter is applied, then only Meetings whose name contains that text are listed.
    - [ ] Given a filter matches no Meetings, when it is applied, then the list states that nothing matched.
    - [ ] Given a Meeting has finished processing, when the Member opens it, then they are prompted to give it a name.
    - [ ] Given the Member does not supply a name, when the prompt is dismissed, then the System applies a name generated from the transcript.
    - [ ] Given a Meeting has a name, when a Member edits it, then the new name is shown everywhere the Meeting is listed.
    - [ ] Given a Meeting is listed, when a Member views it, then its date and time are shown separately from its name and cannot be edited.

- US-014: As a Member, I want to file Meetings into Folders, move them when they are misfiled, and delete the ones that should not be kept, so that the Workspace stays in order and nothing lingers that shouldn't.
  - Acceptance criteria:
    - [ ] Given a Member is in a Workspace, when they create a Folder with a name, then the Folder appears in that Workspace.
    - [ ] Given a Member is creating a Folder, when they choose where it goes, then it cannot be placed inside another Folder.
    - [ ] Given a Meeting is created without a Folder being chosen, when processing starts, then it is placed in the Workspace's default Folder.
    - [ ] Given a Folder holds Meetings, when a Member deletes the Folder, then its Meetings are moved to the default Folder and none of them is deleted.
    - [ ] Given a Workspace holds several Folders, when a Member opens a Folder, then only that Folder's Meetings are listed.
    - [ ] Given a Member opens a Meeting, when they move it to another Folder in the Workspace, then its recording, transcript and notes move with it and its existing notes are unchanged.
    - [ ] Given a Member is choosing where to move a Meeting, when they browse the targets, then only Folders in the same Workspace are offered.
    - [ ] Given a Meeting has been moved to another Folder, when its notes are next generated, then the new Folder's Meetings form its context set.
    - [ ] Given a Member opens a Meeting they recorded, when they delete it and confirm, then its recording, transcript and notes are removed.
    - [ ] Given a Member did not record the Meeting and is not a Moderator, when they open it, then no delete action is available.
    - [ ] Given a Member starts deleting a Meeting, when they do not confirm, then nothing is deleted.
    - [ ] Given a deleted Meeting had been used as context for another Meeting's notes, when those notes are opened, then they are unchanged.

### Sharing

- US-015: As a Moderator, I want to restrict access to a Meeting to selected Workspace members, so that sensitive meetings (such as one-on-ones or interviews) are not visible to the whole Workspace.
  - Acceptance criteria:
    - [ ] Given the Moderator has restricted a Meeting to selected Workspace members, when a member who was not selected opens the Workspace, then the Meeting is not shown to them.
    - [ ] Given a Meeting is restricted, when a Workspace member who was not selected opens the Meeting's direct link, then the System denies access without showing any of its content.
    - [ ] Given a Meeting is restricted, when a selected Workspace member opens it, then they can view its transcript and notes.
    - [ ] Given a Meeting is restricted, when a Workspace member who was not selected requests Meetings through their connected assistant, then the restricted Meeting is not returned.
    - [ ] Given a Workspace member has only the Member role, when they view a Meeting, then they have no option to restrict its access.

- US-016: As a Member, I want to share a Meeting with someone outside the Workspace for reading only, optionally with the speakers' names hidden, so that I can pass on what was said without handing over the record or exposing who said it.
  - Acceptance criteria:
    - [ ] Given a Member opens a Meeting, when they create a share, then they receive a link that grants reading of the transcript and notes and nothing else.
    - [ ] Given a person is not signed in, when they open a share link, then they are asked to sign in and no content is shown beforehand.
    - [ ] Given an instance runs in `invite-only` mode, when a person without an account opens a share link, then they cannot register through it.
    - [ ] Given a signed-in person opens a share link, when the creator has not approved them, then no content is shown and the creator receives an access request.
    - [ ] Given a share is bound to account A, when account B opens the link, then B sees no content.
    - [ ] Given a signed-in recipient opens a share link, when they view the Meeting, then no download, export or re-share action is available to them.
    - [ ] Given a Member revokes a share, when the recipient opens the link again, then access is denied.
    - [ ] Given a Member is creating a share, when they enable redaction, then the recipient sees speaker labels as Speaker 1, Speaker 2 and so on instead of names.
    - [ ] Given a share has redaction enabled, when the recipient opens it, then the recording is not part of the share.

### Export and operations

- US-017: As a Member, I want to download a Meeting's transcript and notes in a portable form, so that I can keep and use them outside the System.
  - Acceptance criteria:
    - [ ] Given the Member has access to a processed Meeting, when they export its transcript, then they download a file with the transcript split by speaker labels.
    - [ ] Given the Meeting's notes have been generated, when the Member exports them, then they download a file with the notes.
    - [ ] Given the Meeting's notes have not been generated yet, when the Member opens the export options, then only the transcript export is available.
    - [ ] Given the transcript has been corrected in the System, when the Member exports it, then the file contains the corrected version.
    - [ ] Given a Member exports the transcript with timestamps turned off, when the file is downloaded, then it carries speaker labels and text without timestamps.
    - [ ] Given a Member exports a transcript or notes, when they open the file, then it opens with a notice that it must not be shared without the participants' permission and ends with a line attributing it to Whadio.
    - [ ] Given the transcript has been edited, when it is downloaded, then the file contains the edited version and states that it was edited.

- US-018: As a User, I want to connect my own AI assistant to the Meetings I can see, so that I can work with them in the tool I already use.
  - Acceptance criteria:
    - [ ] Given a signed-in User opens their settings, when they create an access key for an assistant, then the key is shown to them once and is stored only in hashed form.
    - [ ] Given an AI assistant is connected with a User's key, when it requests Meetings, then only the Meetings that User has access to are returned.
    - [ ] Given a User revokes a key, when an assistant uses that key again, then the request is rejected.
    - [ ] Given a Meeting is restricted and the User is not among the selected members, when their assistant requests it, then it is not returned.

- US-019: As an Administrator, I want a dashboard of the processing queue, failures, load and model usage, so that I can run the service without reading anyone's meetings.
  - Acceptance criteria:
    - [ ] Given an Administrator opens the dashboard, when the queue is not empty, then each job is listed with its Workspace, its state and how long it has been waiting.
    - [ ] Given a processing job has failed, when the Administrator opens the dashboard, then the failure is listed together with its cause.
    - [ ] Given an Administrator opens the dashboard, when they view the system panel, then they see server load and built-in model usage against its limits.
    - [ ] Given an Administrator opens any dashboard view, when they look for meeting content, then no recording, transcript or notes content is shown or reachable.

---

## INVEST screening

- US-001
  - **Independent** — the only story that mentions the login flow
  - **Negotiable** — password rules and session handling open
  - **Valuable** — gives an account and private space
  - **Estimable** — standard authentication plus an emailed link
  - **Small** — one mechanism, the account link, behind several criteria
  - **Testable** — access or denial, directly observable

- US-002
  - **Independent** — the only story that manages membership
  - **Negotiable** — invitation wording and screens left to the team
  - **Valuable** — teams get a shared, governed space
  - **Estimable** — familiar CRUD and role checks
  - **Small** — one subsystem despite many criteria
  - **Testable** — each role's permissions assertable directly

- US-003
  - **Independent** — the only story that captures audio
  - **Negotiable** — capture and handover mechanics open
  - **Valuable** — the product's central capability
  - **Estimable** — bounded; unsupported browsers ruled out
  - **Small** — happy path only, one flow
  - **Testable** — recording and its arrival both observable

- US-004
  - **Independent** — the only story that accepts an uploaded file
  - **Negotiable** — accepted formats left to requirements
  - **Valuable** — covers meetings the extension cannot
  - **Estimable** — ordinary upload with validation
  - **Small** — one upload path, one validation
  - **Testable** — acceptance, rejection and state observable

- US-005
  - **Independent** — the only story that labels speakers
  - **Negotiable** — the renaming interface is unspecified
  - **Valuable** — the reader can tell who spoke
  - **Estimable** — numbered fallback covers Meet changes
  - **Small** — one labelling step plus renaming
  - **Testable** — labels checkable against expected names

- US-006
  - **Independent** — the only story that produces a Meeting's first notes
  - **Negotiable** — the preset set is not fixed
  - **Valuable** — the write-up without the whole transcript
  - **Estimable** — one generation call per preset
  - **Small** — one generation path, four criteria
  - **Testable** — sections present, prompt unreachable

- US-007
  - **Independent** — the only story that builds a context set
  - **Negotiable** — assembly and size limits open
  - **Valuable** — carries recurring topics and actions forward
  - **Estimable** — scope fixed to one Folder
  - **Small** — context assembly and nothing else
  - **Testable** — which transcripts entered is checkable

- US-008
  - **Independent** — the only story that configures a provider
  - **Negotiable** — provider list deliberately left open
  - **Valuable** — the Owner trades quality against privacy
  - **Estimable** — key storage plus a provider switch
  - **Small** — one settings path plus fallback
  - **Testable** — isolation and failure both assertable

- US-009
  - **Independent** — the only story that notifies about processing
  - **Negotiable** — delivery channel deliberately left open
  - **Valuable** — the user stops checking back
  - **Estimable** — one trigger and one message
  - **Small** — one hook on processing completion
  - **Testable** — arrival and its contents inspectable

- US-010
  - **Independent** — the only story that replaces existing notes
  - **Negotiable** — the cap is still to settle
  - **Valuable** — a wrong preset costs nothing
  - **Estimable** — re-runs an existing generation path
  - **Small** — one action plus a counter
  - **Testable** — limit and failure both checkable

- US-011
  - **Independent** — the only story that edits transcript text
  - **Negotiable** — editing surface left to design
  - **Valuable** — an accurate record, nothing lost
  - **Estimable** — rendering plus retaining one original
  - **Small** — one view, one versioning rule
  - **Testable** — both versions retrievable and marked

- US-012
  - **Independent** — the only story that touches the glossary
  - **Negotiable** — biasing mechanism left to implementation
  - **Valuable** — the team's own terms stop breaking
  - **Estimable** — CRUD plus one pipeline hookup
  - **Small** — one list, one recognition hookup
  - **Testable** — terms reaching recognition are checkable

- US-013
  - **Independent** — the only story that names or filters Meetings
  - **Negotiable** — paging and filter interface open
  - **Valuable** — finds a meeting months later
  - **Estimable** — a list, filters, one naming call
  - **Small** — one screen despite many criteria
  - **Testable** — filter results countable and exact

- US-014
  - **Independent** — the only story that moves a Meeting
  - **Negotiable** — how deletion is confirmed is open
  - **Valuable** — keeps the Workspace in order
  - **Estimable** — CRUD, one move, one cascade
  - **Small** — one organisational model, one screen
  - **Testable** — placement and removal directly observable

- US-015
  - **Independent** — the only story that restricts a Meeting
  - **Negotiable** — selection interface left to design
  - **Valuable** — sensitive meetings stay out of sight
  - **Estimable** — one check across the content paths
  - **Small** — a single rule, applied throughout
  - **Testable** — every path testable for denial

- US-016
  - **Independent** — the only story that grants outside access
  - **Negotiable** — link form and expiry open
  - **Valuable** — outsiders read without taking it
  - **Estimable** — a token, an approval step and a read view
  - **Small** — one grant plus one transform
  - **Testable** — approval, revocation and redaction all observable

- US-017
  - **Independent** — the only story that downloads content
  - **Negotiable** — formats deliberately left to requirements
  - **Valuable** — content usable outside the System
  - **Estimable** — serialising already-structured content
  - **Small** — one mechanism with several shapes
  - **Testable** — downloaded files inspectable directly

- US-018
  - **Independent** — the only story that issues an access key
  - **Negotiable** — integration protocol left to requirements
  - **Valuable** — meetings reachable from the user's tool
  - **Estimable** — key issuance plus an access filter
  - **Small** — one key lifecycle, one filter
  - **Testable** — scope and revocation both assertable

- US-019
  - **Independent** — the only story serving the Administrator
  - **Negotiable** — presentation and thresholds left open
  - **Valuable** — the service can be run and diagnosed
  - **Estimable** — reads queue state already recorded
  - **Small** — one read-only view
  - **Testable** — the absence of content is assertable too

- US-020
  - **Independent** — the only story that recovers an account; shares only the link mechanism with US-001
  - **Negotiable** — screens and email wording left open
  - **Valuable** — a forgotten password no longer loses the account
  - **Estimable** — reuses the registration link mechanism
  - **Small** — one request, one link, one form
  - **Testable** — expiry, reuse and ended sessions all observable

---

## AI Usage

This document was prepared and revised with the assistance of Claude Code (Claude Opus 5 and Claude
Opus 5.5). The stories and their acceptance criteria come from the team's working session of
2026-09-19 and from the mini technical specification agreed in Lab 1. The authors reviewed and
edited every story, and the document is reviewed through a pull request before merging.
