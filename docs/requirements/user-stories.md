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
    
- US-001: As a ..., I want ..., so that ...
  - Acceptance criteria:
    - [ ] Given ..., when ..., then ...
    - [ ] ...

## INVEST Check
For each story confirm: Independent, Negotiable, Valuable, Estimable, Small, Testable.

# AI Usage
This document was prepared with the assistance of AI for text paraphrasing and translation. 
The authors provided the original ideas, manually reviewed and edited the content, and verified the accuracy of the final version.