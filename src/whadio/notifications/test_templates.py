from datetime import UTC, datetime, timedelta, timezone
from uuid import UUID

import pytest
from pydantic import HttpUrl, ValidationError

from .templates import (
    AppLinks,
    HostedEviction,
    Locale,
    MailContent,
    Notice,
    ProcessingFailed,
    ProcessingFinished,
    RecordingDeletionWarning,
    ShareAccessRequest,
    render,
)

MEETING_ID = UUID("6f1c2b1e-4d1a-4c4e-9a59-2f7d0c3b8e11")
SHARE_ID = UUID("0b8f4e6a-2c3d-4e5f-8a9b-1c2d3e4f5a6b")
LINKS = AppLinks(HttpUrl("https://whadio.example.com"))
MEETING_LINK = f"https://whadio.example.com/meetings/{MEETING_ID}"

SHARE_REQUEST = ShareAccessRequest(
    share_id=SHARE_ID, requester_name="Olena Koval", requester_email="olena@example.com"
)
DELETION_WARNING = RecordingDeletionWarning(
    meeting_id=MEETING_ID,
    meeting_name="Weekly sync",
    deletes_at=datetime(2026, 11, 1, 9, 30, tzinfo=UTC),
)
NAMED_EVICTION = HostedEviction(meeting_name="Weekly sync")
UNNAMED_EVICTION = HostedEviction(meeting_name=None)
FINISHED = ProcessingFinished(meeting_id=MEETING_ID, meeting_name="Weekly sync")
FAILED = ProcessingFailed(meeting_id=MEETING_ID, meeting_name="Weekly sync")


def _english(notice: Notice) -> MailContent:
    return render(notice, LINKS, Locale.ENGLISH)


@pytest.mark.parametrize(
    ("notice", "link"),
    [
        pytest.param(
            SHARE_REQUEST,
            f"https://whadio.example.com/shares/{SHARE_ID}/access-requests",
            id="share-access-request",
        ),
        pytest.param(DELETION_WARNING, MEETING_LINK, id="recording-deletion-warning"),
        pytest.param(NAMED_EVICTION, "https://whadio.example.com/meetings", id="eviction-named"),
        pytest.param(
            UNNAMED_EVICTION, "https://whadio.example.com/meetings", id="eviction-unnamed"
        ),
        pytest.param(FINISHED, MEETING_LINK, id="processing-finished"),
        pytest.param(FAILED, MEETING_LINK, id="processing-failed"),
    ],
)
def test_mail_body_carries_the_link_of_its_notice(notice: Notice, link: str) -> None:
    # Act
    mail = _english(notice)

    # Assert
    assert f": {link}\n" in mail.body


@pytest.mark.parametrize(
    ("notice", "metadata"),
    [
        pytest.param(
            ShareAccessRequest,
            {"share_id": str(SHARE_ID), "requester_name": "Olena", "requester_email": "o@x.com"},
            id="share-access-request",
        ),
        pytest.param(
            RecordingDeletionWarning,
            {
                "meeting_id": str(MEETING_ID),
                "meeting_name": "Weekly sync",
                "deletes_at": "2026-11-01T09:30:00Z",
            },
            id="recording-deletion-warning",
        ),
        pytest.param(HostedEviction, {"meeting_name": None}, id="hosted-eviction"),
        pytest.param(
            ProcessingFinished,
            {"meeting_id": str(MEETING_ID), "meeting_name": "Weekly sync"},
            id="processing-finished",
        ),
        pytest.param(
            ProcessingFailed,
            {"meeting_id": str(MEETING_ID), "meeting_name": "Weekly sync"},
            id="processing-failed",
        ),
    ],
)
def test_notice_refuses_fields_beyond_its_metadata(
    notice: type[Notice], metadata: dict[str, str | None]
) -> None:
    # Arrange
    payload = {**metadata, "transcript": "We agreed to cut the budget."}

    # Act / Assert
    with pytest.raises(ValidationError, match="transcript"):
        notice.model_validate(payload)


def test_share_access_request_names_the_requesting_account() -> None:
    # Act
    mail = _english(SHARE_REQUEST)

    # Assert
    assert "Olena Koval <olena@example.com> asked for access" in mail.body


def test_deletion_warning_subject_names_the_meeting_and_the_date() -> None:
    # Act
    mail = _english(DELETION_WARNING)

    # Assert
    assert mail.subject == "The recording of “Weekly sync” will be deleted on 2026-11-01"


def test_deletion_warning_states_the_deletion_time_in_utc() -> None:
    # Arrange
    kyiv = timezone(timedelta(hours=2))
    notice = RecordingDeletionWarning(
        meeting_id=MEETING_ID,
        meeting_name="Weekly sync",
        deletes_at=datetime(2026, 11, 1, 1, 30, tzinfo=kyiv),
    )

    # Act
    mail = _english(notice)

    # Assert
    assert "deleted on 2026-10-31 at 23:30 UTC" in mail.body


def test_deletion_warning_without_a_timezone_is_refused() -> None:
    # Act / Assert
    with pytest.raises(ValidationError, match="deletes_at"):
        RecordingDeletionWarning.model_validate(
            {
                "meeting_id": str(MEETING_ID),
                "meeting_name": "Weekly sync",
                "deletes_at": "2026-11-01T09:30:00",
            }
        )


def test_eviction_names_the_meeting_to_a_recipient_who_could_read_it() -> None:
    # Act
    mail = _english(NAMED_EVICTION)

    # Assert
    assert mail.subject == "“Weekly sync” was deleted to stay within the meeting limit"


def test_eviction_names_no_meeting_to_a_recipient_who_could_not_read_it() -> None:
    # Act
    mail = _english(UNNAMED_EVICTION)

    # Assert
    assert "“" not in mail.subject + mail.body


def test_eviction_without_a_name_does_not_print_none() -> None:
    # Act
    mail = _english(UNNAMED_EVICTION)

    # Assert
    assert "None" not in mail.subject + mail.body


def test_processing_finished_subject_names_the_meeting() -> None:
    # Act
    mail = _english(FINISHED)

    # Assert
    assert mail.subject == "“Weekly sync” is ready"


def test_processing_failed_subject_names_the_meeting() -> None:
    # Act
    mail = _english(FAILED)

    # Assert
    assert mail.subject == "Processing failed for “Weekly sync”"


def test_meeting_name_with_line_breaks_stays_on_one_subject_line() -> None:
    # Arrange
    notice = ProcessingFinished(
        meeting_id=MEETING_ID, meeting_name="Weekly\r\nBcc: someone@example.com"
    )

    # Act
    mail = _english(notice)

    # Assert
    assert mail.subject == "“Weekly Bcc: someone@example.com” is ready"


def test_links_keep_the_path_of_the_public_url() -> None:
    # Arrange
    links = AppLinks(HttpUrl("https://example.com/whadio/"))

    # Act
    link = links.meeting(MEETING_ID)

    # Assert
    assert link == f"https://example.com/whadio/meetings/{MEETING_ID}"
