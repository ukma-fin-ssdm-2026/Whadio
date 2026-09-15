# User Stories

Format: As a <role>, I want <capability>, so that <benefit>.

Each story must have acceptance criteria.

## Stories

- US-001: As a user, I want to have access to notes from previous meetings so that I can prevent data loss.
  - Acceptance criteria:
    - [ ] Given the user has no saved meeting notes, when they open the history page, then they see the message "No recordings".
    - [ ] Given the user has saved meeting notes, when they open the history page, then they see a list of their notes with the corresponding date and time of creation.
    - [ ] Given the user is on the history page, when they click on a specific record, then the system opens the summary of that meeting.
    - [ ] Given the user is viewing a long list of notes, when they scroll down the history page, then the system loads additional records via lazy loading to maintain performance.

- US-002: As a user, I want to choose which LLM will process the text so that I can control my privacy better.
  - Acceptance criteria:
    - [ ] Given a meeting is being processed, when no custom LLM is configured, then the system uses a network-isolated local model by default.
    - [ ] Given the user wants to use an external AI model, when they enter their API key in the settings, then the system saves it for future requests.
    - [ ] Given the user is configuring LLM settings, when they open the model selection, then they can choose from the available models via a dropdown menu.
    - [ ] Given the system is processing text with an external API, when an API error occurs, then the system displays an error message and offers a fallback option to use the local model.
    
- US-003: As a user, I want to receive a recording prompt when I join a Google Meet meeting, so that I don't forget to record the meeting for notes.
  - Acceptance criteria:
    - [ ] Given the user has the Google Chrome extension installed, when they join a Google Meet meeting, then the extension displays a prompt with "Record" and "Dismiss" buttons.

- US-004: As a user, I want to have the option to receive notes via email when they are ready, so that I get the result immediately without returning to the platform.
  - Acceptance criteria:
    - [ ] Given the user has the email-notes option enabled, when the meeting notes are ready, then the user receives an email with the notes text and a link to the meeting.

- US-005: As a User, I want to be able to upload meeting recordings, so that I can obtain the meeting transcript and notes even from platforms which the System doesn't support.
  - Acceptance criteria:
    - [ ] Given the User has logged in, when they open one of their Projects, then they can upload a meeting recording to it.
    - [ ] Given the User has uploaded a meeting recording, when the upload finishes, then the System starts processing it and shows the meeting in the Project as being processed.
    - [ ] Given the meeting recording has been uploaded, when the System has finished processing it, then the meeting's transcript and notes are presented to the User.
    - [ ] Given the User selects a file that is not a supported audio recording, when they try to upload it, then the System rejects it with an error message and no meeting is created.
    - [ ] Given an uploaded recording is being processed, when the processing fails, then the meeting is shown in the Project as failed to process.

- US-006: As a Member, I want to download a meeting's transcript and notes as Markdown, so that I can keep them in my own notes.
  - Acceptance criteria:
    - [ ] Given the Member has access to a processed meeting, when they export its transcript, then they download a Markdown file with the transcript split by speaker labels.
    - [ ] Given the meeting's notes have been generated, when the Member exports them, then they download a Markdown file with the notes.
    - [ ] Given the meeting's notes have not been generated yet, when the Member opens the export options, then only the transcript export is available.
    - [ ] Given the transcript has been corrected in the System, when the Member exports it, then the file contains the corrected version.

- US-007: As a Moderator, I want to restrict access to a meeting to selected Project members, so that sensitive meetings (such as one-on-ones or interviews) are not visible to the whole Project.
  - Acceptance criteria:
    - [ ] Given the Moderator has restricted a meeting to selected Project members, when a Project member who was not selected opens the Project, then the meeting is not shown to them.
    - [ ] Given a meeting is restricted, when a Project member who was not selected opens the meeting's direct link, then the System denies access without showing any of its content.
    - [ ] Given a meeting is restricted, when a selected Project member opens it, then they can view its transcript and notes.
    - [ ] Given a meeting is restricted, when a Project member who was not selected requests meetings through their MCP client, then the restricted meeting is not returned.
    - [ ] Given a Project member has only the Member role, when they view a meeting, then they have no option to restrict its access.

- US-008: As an Owner, I want to invite people to my Project with a chosen role, so that my team can work with the Project's meetings and glossary together.
  - Acceptance criteria:
    - [ ] Given the Owner is in their Project, when they invite a person and choose their role, then that person receives an invitation to the Project.
    - [ ] Given a person has received an invitation, when they accept it, then they join the Project with the chosen role and see the meetings accessible to them.
    - [ ] Given a person has received an invitation, when they decline it, then they do not join the Project.
    - [ ] Given a Project member has the Member or Moderator role, when they open the Project, then they have no option to invite people.

## INVEST Check
For each story confirm: Independent, Negotiable, Valuable, Estimable, Small, Testable.

# AI Usage
This document was prepared with the assistance of AI for text paraphrasing and translation. 
The authors provided the original ideas, manually reviewed and edited the content, and verified the accuracy of the final version.
US-006–US-008 and the extra acceptance criteria of US-005 were drafted with Claude Code (Claude Opus 5) from Andrii's outline and reviewed by Andrii before committing.
