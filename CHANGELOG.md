# Changelog

All notable changes to Whadio are recorded here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and versions follow
[Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.21.0] - 2026-11-22

### Added

- Request, approve and read shared meetings from the web app ([#368](https://github.com/ukma-fin-ssdm-2026/Whadio/pull/368))

## [0.20.0] - 2026-11-18

### Added

- Add undo to meeting move notice ([#384](https://github.com/ukma-fin-ssdm-2026/Whadio/pull/384))

## [0.19.0] - 2026-11-18

### Added

- Create, list and revoke meeting shares from the web app ([#367](https://github.com/ukma-fin-ssdm-2026/Whadio/pull/367))

## [0.18.0] - 2026-11-18

### Added

- Regenerate a meeting's notes from the web app ([#393](https://github.com/ukma-fin-ssdm-2026/Whadio/pull/393))

## [0.17.0] - 2026-11-18

### Added

- Keep notes on screen during a regeneration and show earlier versions ([#392](https://github.com/ukma-fin-ssdm-2026/Whadio/pull/392))

## [0.16.0] - 2026-11-17

### Added

- Delete workspaces from web app ([#383](https://github.com/ukma-fin-ssdm-2026/Whadio/pull/383))
- Regenerate a meeting's notes through the API ([#391](https://github.com/ukma-fin-ssdm-2026/Whadio/pull/391))

## [0.15.0] - 2026-11-17

### Added

- Ask the recorder to keep or rename a generated meeting name ([#388](https://github.com/ukma-fin-ssdm-2026/Whadio/pull/388))
- Remember the preset and requester of a notes job ([#390](https://github.com/ukma-fin-ssdm-2026/Whadio/pull/390))

## [0.14.4] - 2026-11-17

### Fixed

- Retain recovery copies after interrupted downloads ([#341](https://github.com/ukma-fin-ssdm-2026/Whadio/pull/341))

## [0.14.3] - 2026-11-17

### Fixed

- Retain recordings when local saving fails ([#340](https://github.com/ukma-fin-ssdm-2026/Whadio/pull/340))

## [0.14.2] - 2026-11-16

### Fixed

- Hold generated meeting names to the display-text rule ([#387](https://github.com/ukma-fin-ssdm-2026/Whadio/pull/387))

## [0.14.1] - 2026-11-16

### Fixed

- Use keyset cursors for workspace and destination lists ([#355](https://github.com/ukma-fin-ssdm-2026/Whadio/pull/355))

## [0.14.0] - 2026-11-16

### Added

- Restrict a meeting to selected members from the web app ([#366](https://github.com/ukma-fin-ssdm-2026/Whadio/pull/366))

## [0.13.0] - 2026-11-15

### Added

- Style the extension like the web app ([#365](https://github.com/ukma-fin-ssdm-2026/Whadio/pull/365))

### Fixed

- Delete expired sessions on every scheduler run ([#327](https://github.com/ukma-fin-ssdm-2026/Whadio/pull/327))
- Harden extension recordings against setup failures and races ([#364](https://github.com/ukma-fin-ssdm-2026/Whadio/pull/364))

## [0.12.1] - 2026-11-10

### Fixed

- Delete expired sessions on every scheduler run ([#327](https://github.com/ukma-fin-ssdm-2026/Whadio/pull/327))

## [0.12.0] - 2026-11-09

### Added

- Rename speakers in the web app ([#313](https://github.com/ukma-fin-ssdm-2026/Whadio/pull/313))
- Add a workspace members page ([#331](https://github.com/ukma-fin-ssdm-2026/Whadio/pull/331))
- Change roles and remove members in the web app ([#333](https://github.com/ukma-fin-ssdm-2026/Whadio/pull/333))

## [0.11.0] - 2026-11-09

### Added

- Correct transcript text in the web app ([#312](https://github.com/ukma-fin-ssdm-2026/Whadio/pull/312))

## [0.10.2] - 2026-11-08

### Fixed

- Recover processing jobs whose result was lost ([#325](https://github.com/ukma-fin-ssdm-2026/Whadio/pull/325))

## [0.10.1] - 2026-11-08

### Fixed

- Bound object storage calls with a timeout and jittered retries ([#323](https://github.com/ukma-fin-ssdm-2026/Whadio/pull/323))
- Recover processing jobs whose message was lost ([#324](https://github.com/ukma-fin-ssdm-2026/Whadio/pull/324))

## [0.10.0] - 2026-11-08

### Added

- Add administrator job monitoring page ([#305](https://github.com/ukma-fin-ssdm-2026/Whadio/pull/305))

## [0.9.0] - 2026-11-08

### Added

- Change a member's role ([#303](https://github.com/ukma-fin-ssdm-2026/Whadio/pull/303))
- Remove a member from a workspace ([#310](https://github.com/ukma-fin-ssdm-2026/Whadio/pull/310))

## [0.8.1] - 2026-11-08

### Fixed

- Give the broker connection and publishes a deadline ([#315](https://github.com/ukma-fin-ssdm-2026/Whadio/pull/315))

## [0.8.0] - 2026-11-08

### Added

- Add workspace invitations frontend ([#309](https://github.com/ukma-fin-ssdm-2026/Whadio/pull/309))

## [0.7.0] - 2026-11-07

### Added

- List workspace members ([#302](https://github.com/ukma-fin-ssdm-2026/Whadio/pull/302))

## [0.6.1] - 2026-11-07

### Fixed

- Pin Swagger UI and check its integrity ([#297](https://github.com/ukma-fin-ssdm-2026/Whadio/pull/297))

## [0.6.0] - 2026-11-05

### Added

- Organise meetings into folders ([#259](https://github.com/ukma-fin-ssdm-2026/Whadio/pull/259))

### Fixed

- Give the extension's and the web app's requests a deadline ([#306](https://github.com/ukma-fin-ssdm-2026/Whadio/pull/306))

## [0.5.0] - 2026-11-05

### Added

- Add registration and password-reset pages ([#304](https://github.com/ukma-fin-ssdm-2026/Whadio/pull/304))

## [0.4.0] - 2026-11-04

### Added

- Add the pr-review agent skill ([#269](https://github.com/ukma-fin-ssdm-2026/Whadio/pull/269))

## [0.3.0] - 2026-11-03

### Added

- Add workspace creation to the web app ([#258](https://github.com/ukma-fin-ssdm-2026/Whadio/pull/258))

## [0.2.1] - 2026-11-03

### Refactoring

- Dispatch the recorder's messages from a table (Replace Conditional with Polymorphism, Extract Function) ([#285](https://github.com/ukma-fin-ssdm-2026/Whadio/pull/285))

## [0.2.0] - 2026-11-03

### Added

- Add the ui-evidence agent skill and a capture script ([#268](https://github.com/ukma-fin-ssdm-2026/Whadio/pull/268))

## [0.1.2] - 2026-11-03

### Refactoring

- Extract capture assembly from the event loop (Extract Function) ([#279](https://github.com/ukma-fin-ssdm-2026/Whadio/pull/279))

## [0.1.1] - 2026-11-03

### Refactoring

- Replace the trailing-slash regex with a backward scan (Substitute Algorithm) ([#267](https://github.com/ukma-fin-ssdm-2026/Whadio/pull/267))
- Take the CI database password from .env (Move Sensitive Data Out of Code) ([#273](https://github.com/ukma-fin-ssdm-2026/Whadio/pull/273))
- Extract the upload steps from Upload.send (Extract Function) ([#276](https://github.com/ukma-fin-ssdm-2026/Whadio/pull/276))

## [0.1.0] - 2026-11-02

The version graded at the midterm (`bc3ec99`, also tagged `midterm-project-2026-11-02`), the
first one with a version tag. Its changes are in the commit history before `v0.1.0`.

### Added

- Recording a Google Meet call from the Chrome extension, or uploading a recording, into a
  workspace folder.
- Transcription with speaker separation, and notes written by a local or hosted LLM.
- Workspaces with roles, folders, restricted meetings, shares and access requests, behind the
  REST API, the web app and an MCP server.
- Audit events, retention of recordings, and notification mail.
