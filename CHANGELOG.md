# Changelog

All notable changes to Whadio are recorded here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and versions follow
[Semantic Versioning](https://semver.org/spec/v2.0.0.html).

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
