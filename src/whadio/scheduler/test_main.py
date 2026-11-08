import asyncio
from datetime import datetime, timedelta
from pathlib import Path
from uuid import uuid4

import pytest

from ..processing.settings import JobRecoverySettings
from ..shared.database import IUseCaseTransactions
from . import main


def test_scheduler_runtime_runs_job_recovery_with_its_configured_limit(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    # Arrange
    built: list[timedelta] = []
    ran: list[datetime] = []

    class RecordedRecovery:
        def __init__(self, database: IUseCaseTransactions, settings: JobRecoverySettings) -> None:
            del database
            built.append(settings.unstarted_limit)

        async def recover(self, now: datetime) -> int:
            ran.append(now)
            return 0

    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("WHADIO_SMTP__HOST", raising=False)
    environment = {
        "WHADIO_JOB_RECOVERY__UNSTARTED_LIMIT": "PT1M",
        # Nothing listens on port 1, so every other job of the tick fails fast and is counted.
        "WHADIO_DB_HOST": "127.0.0.1",
        "WHADIO_DB_PORT": "1",
        "WHADIO_DB_APP_PASSWORD": uuid4().hex,
        "WHADIO_STORAGE__ENDPOINT_URL": "http://127.0.0.1:1",
        "WHADIO_STORAGE__ACCESS_KEY": "whadio-test",
        "WHADIO_STORAGE__SECRET_KEY": uuid4().hex,
    }
    for name, value in environment.items():
        monkeypatch.setenv(name, value)
    monkeypatch.setattr(main, "JobRecoveryJobs", RecordedRecovery)
    # Act
    asyncio.run(main.run(once=True))
    # Assert
    assert (built, len(ran)) == ([timedelta(minutes=1)], 1)
