# Boundary Cases

Boundary value analysis puts test values on the edges of an input range, where an off-by-one
mistake such as `<` written for `<=` shows up. The course page `Reference/Equivalence-Boundary.md`
(Lecture 7, §6.2) describes the technique. This list complements the
[edge cases](testing.md#edge-cases-covered) of the unit testing report, which covers refusals and
unusual states rather than numeric limits.

## Technique

- **3-point** for a one-sided boundary: just below, on and just above it.
- **7-point** for a two-sided range `[min, max]`: `min − 1`, `min`, `min + 1`, a nominal value,
  `max − 1`, `max` and `max + 1`.

The step is the smallest one the type can tell apart: one item or character for counts and
lengths, one second for presigned links, one microsecond for `timedelta` settings, and the smallest
positive float `ε` (`math.ulp(0.0)`) for floors at zero and segment times, and the neighbouring
floats (`math.nextafter`) for other float floors. Each parametrised case has
an id that starts with `bva-` and names the point, such as `bva-below-max`, so a failure names the
technique and the edge it broke. All the tests are fast: they need no database, broker or storage.

Where a point was already tested before this pass, the table names that test instead of repeating
it.

## Boundaries

| # | Constraint | Where | Technique | Values | Tests |
|---|---|---|---|---|---|
| 1 | Retention pass asks for another page only after a full one: `len(due) < BATCH_SIZE`, `BATCH_SIZE = 100` | [`retention/services.py`](../../src/whadio/retention/services.py) `run`, `remove_deleted_meeting_recordings`; the constant in [`meetings/retention.py`](../../src/whadio/meetings/retention.py) | 3-point | 99, 100, 101 due recordings and pending deletions: each handled once; 1, 2 and 2 page queries | [`retention/test_services.py`](../../src/whadio/retention/test_services.py): `test_retention_pass_deletes_every_due_recording_once_across_pages`, `test_retention_pass_asks_for_another_page_only_after_a_full_one`, `test_cleanup_removes_every_pending_recording_once_across_pages`, `test_cleanup_asks_for_another_page_only_after_a_full_one` |
| 2 | Processing retry cap | `processing/services.py` | 3-point | 4, 5, 6 attempts | Covered by the retry-limit regression test of the debugging log pull request (#100), not here |
| 3 | Page size `1 ≤ limit ≤ 100` | [`api/core/schemas.py`](../../src/whadio/api/core/schemas.py) `PageQuery` | 7-point | 0, 1, 2, 50, 99, 100, 101 | [`api/core/test_schemas.py`](../../src/whadio/api/core/test_schemas.py): `test_page_size_is_accepted_only_from_1_to_100` |
| 3 | Cursor length 1 to 4096 characters | [`api/core/schemas.py`](../../src/whadio/api/core/schemas.py) `PageQuery` | 7-point | 0, 1, 2, 64, 4095, 4096, 4097 | [`api/core/test_schemas.py`](../../src/whadio/api/core/test_schemas.py): `test_cursor_is_accepted_only_from_1_to_4096_characters` |
| 4 | Workspace name 1 to 100 characters | [`api/accounts/schemas.py`](../../src/whadio/api/accounts/schemas.py) `WorkspaceName` | 7-point, and padded at 100 and 101 | 0, 1, 2, 50, 99, 100, 101 | [`api/accounts/test_schemas.py`](../../src/whadio/api/accounts/test_schemas.py): `test_workspace_name_is_accepted_only_from_1_to_100_characters`, `test_padding_around_a_workspace_name_does_not_count_toward_its_length` |
| 4 | Folder name 1 to 100 characters | [`api/meetings/routes_content.py`](../../src/whadio/api/meetings/routes_content.py) `FolderInput` | 7-point, and padded at 100 and 101 | 0, 1, 2, 50, 99, 100, 101 | [`api/meetings/test_routes_content.py`](../../src/whadio/api/meetings/test_routes_content.py): `test_folder_name_is_accepted_only_from_1_to_100_characters`, `test_padding_around_a_folder_name_does_not_count_toward_its_length` |
| 4 | Meeting name 1 to 200 characters | [`api/meetings/schemas.py`](../../src/whadio/api/meetings/schemas.py) `MeetingName` | 7-point, and padded at 200 and 201 | 0, 1, 2, 100, 199, 200, 201 | [`api/meetings/test_schemas.py`](../../src/whadio/api/meetings/test_schemas.py): `test_meeting_name_is_accepted_only_from_1_to_200_characters`, `test_padding_around_a_meeting_name_does_not_count_toward_its_length` |
| 4 | Glossary term and preferred spelling 1 to 200 characters, on create and update | [`api/meetings/routes_content.py`](../../src/whadio/api/meetings/routes_content.py) `TermInput`, `TermPatch` | 7-point, and padded at 200 and 201 | 0, 1, 2, 100, 199, 200, 201 | [`api/meetings/test_routes_content.py`](../../src/whadio/api/meetings/test_routes_content.py): `test_glossary_spelling_is_accepted_only_from_1_to_200_characters`, `test_padding_around_a_glossary_spelling_does_not_count_toward_its_length` |
| 4 | Glossary description at most 2000 characters, on create and update | [`api/meetings/routes_content.py`](../../src/whadio/api/meetings/routes_content.py) `TermInput`, `TermPatch` | 3-point | 1999, 2000, 2001 | [`api/meetings/test_routes_content.py`](../../src/whadio/api/meetings/test_routes_content.py): `test_glossary_description_is_accepted_up_to_2000_characters` |
| 4 | Sign-in email at most 254 characters | [`api/accounts/schemas.py`](../../src/whadio/api/accounts/schemas.py) `SignIn` | 3-point | 253, 254, 255 | [`api/accounts/test_schemas.py`](../../src/whadio/api/accounts/test_schemas.py): `test_sign_in_email_is_accepted_up_to_254_characters` |
| 5 | Notes title 1 to 200 characters, after its spaces are collapsed | [`workers/notes/output.py`](../../src/whadio/workers/notes/output.py) `MAX_NAME_LENGTH` | 7-point | 0 and 201 (existing), 1, 2, 100, 199, 200; a 204-character title that collapses to 200 | [`workers/notes/test_output.py`](../../src/whadio/workers/notes/test_output.py): `test_title_of_1_to_200_characters_becomes_the_name`, `test_title_spaces_are_collapsed_before_its_length_is_counted`; `test_notes_that_break_the_format_are_refused_as_invalid_output` (`empty name`, `name too long`) |
| 5 | Proposed meeting name 1 to 200 characters | [`contracts/notes.py`](../../src/whadio/contracts/notes.py) `MeetingName` | 7-point | 0, 1, 2, 100, 199, 200, 201 (existing) | [`contracts/test_notes.py`](../../src/whadio/contracts/test_notes.py): `test_proposed_name_of_1_to_200_characters_is_accepted`, `test_empty_proposed_name_is_refused`, `test_proposed_name_longer_than_200_characters_is_refused` |
| 6 | At most 20 context meetings | [`contracts/notes.py`](../../src/whadio/contracts/notes.py) `MAX_CONTEXT_MEETINGS` | 3-point | 19, 20, 21 (existing) | [`contracts/test_notes.py`](../../src/whadio/contracts/test_notes.py): `test_notes_request_with_up_to_20_context_meetings_is_accepted`, `test_notes_request_with_too_many_context_meetings_is_refused` |
| 7 | Presigned link lifetime from 1 s to 7 days | [`shared/storage.py`](../../src/whadio/shared/storage.py) `S3ObjectStorage.presign_get` | 7-point; the nominal value is the existing 30-minute test | 0 (existing), 999 ms, 1 s, 2 s, 7 d − 1 s, 7 d, 7 d + 1 s (existing) | [`shared/test_storage.py`](../../src/whadio/shared/test_storage.py): `test_presigned_url_lives_from_one_second_to_seven_days`, `test_presigning_refuses_a_lifetime_under_one_second`, `test_presigning_refuses_a_lifetime_outside_what_sigv4_allows`, `test_presigned_url_carries_the_requested_lifetime` |
| 8 | Notes limits: `max_output_tokens ≥ 1024`, `max_input_tokens ≥ 1000`, `concurrency ≥ 1`, finite `chars_per_token ≥ 0.25` | [`workers/notes/settings.py`](../../src/whadio/workers/notes/settings.py) `NotesSettings` | 3-point each | 1023, 1024, 1025; 999, 1000, 1001; 0, 1, 2; the floats either side of 0.25 and 0.25 itself, and infinity | [`workers/notes/test_settings.py`](../../src/whadio/workers/notes/test_settings.py): `test_notes_limit_is_refused_only_below_its_floor`, `test_infinite_chars_per_token_is_refused`; [`workers/notes/test_prompt.py`](../../src/whadio/workers/notes/test_prompt.py): `test_meeting_over_the_budget_at_the_smallest_chars_per_token_is_refused` |
| 8 | Ollama limits: `num_ctx ≥ 2048`, `keep_alive ≥ 0` | [`workers/notes/settings.py`](../../src/whadio/workers/notes/settings.py) `OllamaSettings` | 3-point each | 2047, 2048, 2049; −1 µs, 0, 1 µs | [`workers/notes/test_settings.py`](../../src/whadio/workers/notes/test_settings.py): `test_ollama_limit_is_refused_only_below_its_floor` |
| 8 | ASR limits: `beam_size`, `embedding_batch_size`, `max_audio_bytes`, `slots` at least 1; at least 2 candidate languages | [`workers/asr/settings.py`](../../src/whadio/workers/asr/settings.py) `AsrSettings` | 3-point each | 0, 1, 2 for each count; 1 (existing), 2, 3 languages | [`workers/asr/test_settings.py`](../../src/whadio/workers/asr/test_settings.py): `test_asr_limit_is_refused_only_below_its_floor`, `test_settings_with_a_single_candidate_language_are_refused` |
| 8 | Retention interval above zero seconds | [`scheduler/settings.py`](../../src/whadio/scheduler/settings.py) `SchedulerSettings` | 3-point | −ε, 0, ε | [`scheduler/test_settings.py`](../../src/whadio/scheduler/test_settings.py): `test_retention_interval_must_be_above_zero` |
| 8 | Bucket name at least 3 characters | [`shared/storage.py`](../../src/whadio/shared/storage.py) `ObjectStorageSettings` | 3-point | 2, 3, 4 | [`shared/test_storage.py`](../../src/whadio/shared/test_storage.py): `test_bucket_name_needs_at_least_3_characters` |
| 8 | Database port 1 to 65535 | [`shared/database.py`](../../src/whadio/shared/database.py) `ConnectionSettings` | 7-point | 0, 1, 2, 5432, 65534, 65535, 65536 | [`shared/test_database.py`](../../src/whadio/shared/test_database.py): `test_database_port_is_accepted_only_from_1_to_65535` |
| 9 | Segment starts at or after zero | [`contracts/common.py`](../../src/whadio/contracts/common.py) `Segment` | 3-point | −ε, 0, ε | [`contracts/test_common.py`](../../src/whadio/contracts/test_common.py): `test_segment_starting_at_or_after_the_recording_start_is_accepted`, `test_segment_starting_before_the_recording_start_is_refused` |
| 9 | Segment ends after it starts | [`contracts/common.py`](../../src/whadio/contracts/common.py) `Segment` | 3-point | end = start − 1 s (existing), end = start (existing), end = start + one float step | [`contracts/test_common.py`](../../src/whadio/contracts/test_common.py): `test_segment_ending_before_it_starts_is_refused`, `test_segment_of_zero_length_is_refused`, `test_segment_ending_just_after_it_starts_is_accepted` |

The schema tests use `refused_fields` from the root `conftest.py`. It returns the fields a model
refuses, so a refusal is checked against the field that holds the boundary and not against any
error.

## What the boundaries showed

One boundary failed. The notes settings accepted any `chars_per_token` above zero, but the prompt
estimate divides by it: below about 5.6 × 10⁻³⁰⁹ the division overflows to infinity, and every
notes job failed with an `OverflowError` instead of a notes failure. Infinity was accepted too and
turned the budget off. The floor is now 0.25, the most cautious ratio a byte-level tokenizer can
need (one token per byte at worst, a character at most four bytes), and infinity is refused. The
schema test had checked the declaration alone; the prompt builder test now checks the value where
it is used.

Every other limit sits where its declaration says. Three behaviours are worth knowing:

- **Padding does not count.** A name padded with Unicode white space (`" 　\t"` on both
  sides) is accepted at the maximum and refused one character past it, because the shared display
  text rule strips the padding before the length is checked.
- **A notes title is measured after its spaces collapse.** A 204-character title line with runs
  of spaces becomes a 200-character name and is accepted.
- **Presigned links live at least one second.** `presign_get` itself accepts any lifetime above
  zero, but the S3 client refuses one under a second with its own `ValueError`. Two consequences
  follow, neither reachable today because both callers ask for whole minutes:
  `InMemoryObjectStorage` accepts a sub-second lifetime that the real storage refuses, and a
  lifetime with a fraction of a second, such as 1.5 s, is signed as 1 s while `expires_at` reports
  1.5 s.

## Not covered here

- Password length (1 to 128) is left to a teammate's test-driven development work.
- The prompt budgets of the notes worker are covered by the mutation testing work.
- Other declared limits have no boundary test yet: the SMTP port (`notifications/settings.py`),
  the speaker display name (200), the share token (256), the MCP key lifetime (1 to 365 days), the
  MCP search limit (1 to 50) and query (2 to 200 characters), and the meeting list name filter
  (1 to 200).

## AI Usage

Drafted with Claude Code (Claude Opus 5.5); checked by Andrii Shalaiev.
