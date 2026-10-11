from uuid import UUID

import pytest
from sqlalchemy.orm import Session

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
