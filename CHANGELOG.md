# Changelog

All notable changes to Whadio are recorded here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and versions follow
[Semantic Versioning](https://semver.org/spec/v2.0.0.html).

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

- Dispatch the recorder's messages from a table ([#285](https://github.com/ukma-fin-ssdm-2026/Whadio/pull/285))

## [0.2.0] - 2026-11-03

### Added

- Add the ui-evidence agent skill and a capture script ([#268](https://github.com/ukma-fin-ssdm-2026/Whadio/pull/268))

## [0.1.2] - 2026-11-03

### Refactoring

- Extract capture assembly from the event loop ([#279](https://github.com/ukma-fin-ssdm-2026/Whadio/pull/279))

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
