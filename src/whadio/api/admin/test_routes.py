import asyncio
from datetime import UTC, datetime
from uuid import uuid4

import pytest
from sqlalchemy import select

from ...accounts.administrators import AdministratorRepository, AdministratorService
from ...processing.enums import JobStatus, JobType
from ...processing.models import ProcessingJob
from ...processing.monitoring import JobSnapshot
from ...processing.repositories import JobRepository
from ...shared.database import DatabaseSettings
from ..core.schemas import Page
from ..test_composition import client_fixture, unit_fixture
from .routes import MetricsRead

pytestmark = pytest.mark.slow


@pytest.mark.parametrize("actor", ["owner", "member"])
@pytest.mark.parametrize("endpoint", ["jobs", "metrics"])
def test_workspace_roles_do_not_grant_instance_admin_access(
    database_settings: DatabaseSettings, actor: str, endpoint: str
) -> None:
    # Arrange
    async def scenario() -> int:
        async with (
            unit_fixture(database_settings) as unit,
            client_fixture(unit, unit.owner if actor == "owner" else unit.member) as client,
        ):
            # Act
            response = await client.get(f"/api/v1/admin/{endpoint}")
            return response.status_code

    found = asyncio.run(scenario(), loop_factory=asyncio.SelectorEventLoop)
    # Assert
    assert found == 403


def test_administrator_reads_operational_jobs_without_content_access(
    database_settings: DatabaseSettings,
) -> None:
    # Arrange
    async def scenario() -> tuple[int, int, bool, bool]:
        async with unit_fixture(database_settings) as unit:
            await AdministratorService(AdministratorRepository(unit.session)).set_enabled(
                unit.outsider, enabled=True
            )
            job = ProcessingJob(
                processing_job_id=uuid4(),
                meeting_id=unit.meeting,
                job_type=JobType.NOTES,
                status=JobStatus.FAILED,
                failure_reason="original Alice private provider body",
                sent_context=[{"content": "private context"}],
            )
            unit.session.add(job)
            await unit.session.flush()
            async with client_fixture(unit, unit.outsider) as client:
                # Act
                jobs = await client.get("/api/v1/admin/jobs")
                content = await client.get(f"/api/v1/meetings/{unit.meeting}/transcript/export")
                body = jobs.text
                return (
                    jobs.status_code,
                    content.status_code,
                    str(unit.workspace) in body,
                    all(
                        value not in body
                        for value in ("Alice", "private", "sent_context", "meeting_id")
                    ),
                )

    found = asyncio.run(scenario(), loop_factory=asyncio.SelectorEventLoop)
    # Assert
    assert found == (200, 404, True, True)


def test_admin_revocation_takes_effect_without_signing_out(
    database_settings: DatabaseSettings,
) -> None:
    # Arrange
    async def scenario() -> tuple[int, int]:
        async with unit_fixture(database_settings) as unit:
            service = AdministratorService(AdministratorRepository(unit.session))
            await service.set_enabled(unit.member, enabled=True)
            async with client_fixture(unit, unit.member) as client:
                before = await client.get("/api/v1/admin/metrics")
                # Act
                await service.set_enabled(unit.member, enabled=False)
                after = await client.get("/api/v1/admin/metrics")
                return before.status_code, after.status_code

    found = asyncio.run(scenario(), loop_factory=asyncio.SelectorEventLoop)
    # Assert
    assert found == (200, 403)


def test_jobs_cursor_has_stable_ties_and_cannot_cross_filters(
    database_settings: DatabaseSettings,
) -> None:
    # Arrange
    async def scenario() -> tuple[bool, int]:
        async with unit_fixture(database_settings) as unit:
            await AdministratorService(AdministratorRepository(unit.session)).set_enabled(
                unit.owner, enabled=True
            )
            now = datetime.now(UTC)
            identifiers = [uuid4() for _ in range(3)]
            unit.session.add_all(
                [
                    ProcessingJob(
                        processing_job_id=identifier,
                        meeting_id=unit.meeting,
                        job_type=JobType.TRANSCRIPTION,
                        status=JobStatus.QUEUED,
                        created_at=now,
                    )
                    for identifier in identifiers
                ]
            )
            await unit.session.flush()
            async with client_fixture(unit, unit.owner) as client:
                # Act
                first = await client.get(
                    "/api/v1/admin/jobs", params={"limit": 1, "workspace_id": str(unit.workspace)}
                )
                cursor = Page[JobSnapshot].model_validate_json(first.content).pagination.next_cursor
                if cursor is None:
                    raise AssertionError("Expected another page")
                second = await client.get(
                    "/api/v1/admin/jobs",
                    params={"limit": 1, "workspace_id": str(unit.workspace), "cursor": cursor},
                )
                mismatch = await client.get(
                    "/api/v1/admin/jobs", params={"limit": 1, "status": "failed", "cursor": cursor}
                )
                found = [first.json()["items"][0]["job_id"], second.json()["items"][0]["job_id"]]
                return found == [
                    str(value) for value in sorted(identifiers, reverse=True)[:2]
                ], mismatch.status_code

    found = asyncio.run(scenario(), loop_factory=asyncio.SelectorEventLoop)
    # Assert
    assert found == (True, 422)


def test_retained_failed_counts_disappear_when_meeting_is_deleted(
    database_settings: DatabaseSettings,
) -> None:
    # Arrange
    async def scenario() -> tuple[int, int]:
        async with unit_fixture(database_settings) as unit:
            job_id = await JobRepository(unit.session).add(unit.meeting, JobType.NOTES)
            await JobRepository(unit.session).finish(
                job_id, JobStatus.FAILED, datetime.now(UTC), "timed_out"
            )
            before = len(
                list(
                    await unit.session.scalars(
                        select(ProcessingJob).where(ProcessingJob.processing_job_id == job_id)
                    )
                )
            )
            # Act
            await unit.meetings.delete(unit.owner, unit.meeting, datetime.now(UTC))
            after = len(
                list(
                    await unit.session.scalars(
                        select(ProcessingJob).where(ProcessingJob.processing_job_id == job_id)
                    )
                )
            )
            return before, after

    found = asyncio.run(scenario(), loop_factory=asyncio.SelectorEventLoop)
    # Assert
    assert found == (1, 0)


def test_administrator_job_metrics_work_without_telemetry(
    database_settings: DatabaseSettings, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Arrange
    monkeypatch.setenv("WHADIO_ADMIN__SOURCES", "invalid-telemetry-config")
    monkeypatch.setenv("WHADIO_TELEMETRY__RECEIVER", "not-a-url")

    async def scenario() -> tuple[int, str, bool, bool]:
        async with unit_fixture(database_settings) as unit:
            await AdministratorService(AdministratorRepository(unit.session)).set_enabled(
                unit.member, enabled=True
            )
            await JobRepository(unit.session).add(unit.meeting, JobType.NOTES)
            async with client_fixture(unit, unit.member) as client:
                # Act
                response = await client.get("/api/v1/admin/metrics")
                body = MetricsRead.model_validate_json(response.content)
                return (
                    response.status_code,
                    response.headers["Cache-Control"],
                    body.status == "ok" and body.jobs[0].queued == 1,
                    set(body.model_dump()) == {"generated_at", "status", "jobs"},
                )

    found = asyncio.run(scenario(), loop_factory=asyncio.SelectorEventLoop)
    # Assert
    assert found == (200, "no-store", True, True)
