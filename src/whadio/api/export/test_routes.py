import asyncio
from datetime import UTC, datetime

import pytest
from sqlalchemy import delete

from ...meetings.models import Note
from ...meetings.services import TranscriptEdit
from ...shared.database import DatabaseSettings
from ..core.errors import ErrorResponse
from ..test_composition import client_fixture, unit_fixture

pytestmark = pytest.mark.slow


@pytest.mark.parametrize("format_name", ["markdown", "vtt"])
def test_download_current_and_original_preserves_provenance(
    database_settings: DatabaseSettings, monkeypatch: pytest.MonkeyPatch, format_name: str
) -> None:
    # Arrange
    monkeypatch.setenv("WHADIO_EXPORT_PUBLIC_ORIGIN", "https://canonical.example")

    async def scenario() -> tuple[int, bool, bool, bool, str, bool]:
        async with unit_fixture(database_settings) as unit:
            await unit.meetings.edit_transcript(
                unit.member,
                unit.meeting,
                TranscriptEdit(
                    unit.revision,
                    {unit.segment: "\u041f\u0440\u0438\u0432\u0456\u0442 corrected"},
                    {unit.speaker: "Corrected speaker"},
                ),
                datetime.now(UTC),
            )
            async with client_fixture(unit, unit.member) as client:
                # Act
                current = await client.get(
                    f"/api/v1/meetings/{unit.meeting}/transcript/export",
                    params={"format": format_name},
                    headers={"Host": "attacker.example"},
                )
                original = await client.get(
                    f"/api/v1/meetings/{unit.meeting}/transcript/export",
                    params={"format": format_name, "version": "original"},
                )
                return (
                    current.status_code,
                    "corrected" in current.text and "Edited transcript." in current.text,
                    "original" in original.text
                    and "Original transcript." in original.text
                    and "Edited transcript." not in original.text,
                    "canonical.example" in current.headers["Link"]
                    and "attacker.example" not in current.text,
                    current.headers["Cache-Control"],
                    current.headers["content-type"].startswith(
                        "text/vtt" if format_name == "vtt" else "text/markdown"
                    )
                    and "charset=utf-8" in current.headers["content-type"]
                    and current.headers["content-disposition"].startswith("attachment;")
                    and "\u041f\u0440\u0438\u0432\u0456\u0442".encode() in current.content,
                )

    found = asyncio.run(scenario(), loop_factory=asyncio.SelectorEventLoop)
    # Assert
    assert found == (200, True, True, True, "no-store", True)


@pytest.mark.parametrize(
    "query", ["format=pdf", "format=docx", "version=other", "timestamps=perhaps"]
)
def test_download_refuses_unsupported_options(
    database_settings: DatabaseSettings, query: str
) -> None:
    # Arrange
    async def scenario() -> int:
        async with (
            unit_fixture(database_settings) as unit,
            client_fixture(unit, unit.member) as client,
        ):
            # Act
            response = await client.get(
                f"/api/v1/meetings/{unit.meeting}/transcript/export?{query}"
            )
            return response.status_code

    found = asyncio.run(scenario(), loop_factory=asyncio.SelectorEventLoop)
    # Assert
    assert found == 422


def test_notes_download_without_notes_returns_standard_conflict(
    database_settings: DatabaseSettings,
) -> None:
    # Arrange
    async def scenario() -> tuple[int, str]:
        async with unit_fixture(database_settings) as unit:
            await unit.session.execute(delete(Note).where(Note.meeting_id == unit.meeting))
            async with client_fixture(unit, unit.member) as client:
                # Act
                response = await client.get(f"/api/v1/meetings/{unit.meeting}/notes/export")
                return response.status_code, ErrorResponse.model_validate_json(
                    response.content
                ).error.code.value

    found = asyncio.run(scenario(), loop_factory=asyncio.SelectorEventLoop)
    # Assert
    assert found == (409, "NO_NOTES")


@pytest.mark.parametrize("version", ["current", "original"])
def test_original_and_current_download_recheck_restricted_membership(
    database_settings: DatabaseSettings, version: str
) -> None:
    # Arrange
    async def scenario() -> int:
        async with unit_fixture(database_settings) as unit:
            await unit.access.replace_access(
                unit.owner, unit.meeting, {unit.member}, datetime.now(UTC), restricted=True
            )
            async with client_fixture(unit, unit.owner) as client:
                # Act
                response = await client.get(
                    f"/api/v1/meetings/{unit.meeting}/transcript/export",
                    params={"version": version},
                )
                return response.status_code

    found = asyncio.run(scenario(), loop_factory=asyncio.SelectorEventLoop)
    # Assert
    assert found == 404
