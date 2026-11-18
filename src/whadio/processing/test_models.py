from typing import Literal
from uuid import UUID

import pytest
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from ..accounts.enums import NotesTemplate
from .enums import JobStatus, JobType
from .models import ProcessingJob


@pytest.mark.slow
def test_processing_retry_count_defaults_to_zero(
    database_session: Session,
    meeting_id: UUID,
) -> None:
    # Arrange
    job = ProcessingJob(
        meeting_id=meeting_id, job_type=JobType.TRANSCRIPTION, status=JobStatus.QUEUED
    )
    database_session.add(job)
    # Act
    database_session.flush()
    # Assert
    assert job.attempts == 0


@pytest.mark.slow
def test_transcription_job_cannot_carry_a_notes_request(
    database_session: Session,
    meeting_id: UUID,
    owner_id: UUID,
) -> None:
    # Arrange
    database_session.add(
        ProcessingJob(
            meeting_id=meeting_id,
            job_type=JobType.TRANSCRIPTION,
            status=JobStatus.QUEUED,
            template=NotesTemplate.INTERVIEW,
            requested_by_user_id=owner_id,
        )
    )
    # Act
    with pytest.raises(IntegrityError) as failure:
        database_session.flush()
    # Assert
    assert "ck_processing_job_notes_request" in str(failure.value.orig)


@pytest.mark.slow
@pytest.mark.parametrize("missing", ["requester", "preset"])
def test_notes_job_carries_its_preset_and_requester_together(
    database_session: Session,
    meeting_id: UUID,
    owner_id: UUID,
    missing: Literal["requester", "preset"],
) -> None:
    # Arrange
    database_session.add(
        ProcessingJob(
            meeting_id=meeting_id,
            job_type=JobType.NOTES,
            status=JobStatus.QUEUED,
            template=None if missing == "preset" else NotesTemplate.INTERVIEW,
            requested_by_user_id=None if missing == "requester" else owner_id,
        )
    )
    # Act
    with pytest.raises(IntegrityError) as failure:
        database_session.flush()
    # Assert
    assert "ck_processing_job_notes_request" in str(failure.value.orig)
