# Whadio frontend MVP

This is Zlata's Web SPA slice for the Lab 4 upload-driven MVP.

Open `index.html` in a browser. It uses static fixtures that mirror the current FastAPI stubs:

- demo user and workspaces from `src/whadio/api/accounts/fixtures.py`;
- meeting states, upload source, transcript and notes shape from `src/whadio/api/meetings/`;
- the agreed MVP flow from the 2026-10-06 planning transcript: upload a recording, show queued
  processing, then read transcript and notes for processed meetings.

The prototype is dependency-free for now, so it does not add a separate Node toolchain before the
team agrees on frontend linting, formatting and build tasks.
