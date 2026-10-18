from datetime import datetime
from typing import Protocol
from uuid import UUID

from pydantic import JsonValue
from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from .enums import CaptureStatus
from .models import CaptureChunk, CaptureSession


class ICaptureRepository(Protocol):
    async def open(self, meeting_id: UUID, user_id: UUID, now: datetime, /) -> CaptureSession: ...

    async def get(self, capture_id: UUID, /, *, lock: bool = False) -> CaptureSession | None: ...

    async def chunks(self, capture_id: UUID, /) -> list[CaptureChunk]: ...

    async def chunk(self, capture_id: UUID, seq: int, /) -> CaptureChunk | None: ...

    async def meeting_chunks(self, meeting_id: UUID, /) -> list[CaptureChunk]: ...

    async def add_chunk(
        self,
        capture_id: UUID,
        seq: int,
        storage_key: str,
        speaker_events: JsonValue,
        now: datetime,
        /,
    ) -> None: ...

    async def close(
        self, capture_id: UUID, status: CaptureStatus, last_seq: int, now: datetime, /
    ) -> None: ...


class CaptureRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session: AsyncSession = session

    async def open(self, meeting_id: UUID, user_id: UUID, now: datetime) -> CaptureSession:
        capture = CaptureSession(
            meeting_id=meeting_id,
            opened_by_user_id=user_id,
            status=CaptureStatus.RECORDING,
            created_at=now,
        )
        self._session.add(capture)
        await self._session.flush()
        return capture

    async def get(self, capture_id: UUID, *, lock: bool = False) -> CaptureSession | None:
        statement = select(CaptureSession).where(CaptureSession.capture_session_id == capture_id)
        if lock:
            statement = statement.with_for_update().execution_options(populate_existing=True)
        return await self._session.scalar(statement)

    async def chunks(self, capture_id: UUID) -> list[CaptureChunk]:
        found = await self._session.scalars(
            select(CaptureChunk)
            .where(CaptureChunk.capture_session_id == capture_id)
            .order_by(CaptureChunk.seq)
        )
        return list(found)

    async def chunk(self, capture_id: UUID, seq: int) -> CaptureChunk | None:
        return await self._session.scalar(
            select(CaptureChunk).where(
                CaptureChunk.capture_session_id == capture_id, CaptureChunk.seq == seq
            )
        )

    async def meeting_chunks(self, meeting_id: UUID) -> list[CaptureChunk]:
        found = await self._session.scalars(
            select(CaptureChunk)
            .join(CaptureSession)
            .where(CaptureSession.meeting_id == meeting_id)
            .order_by(CaptureChunk.seq)
        )
        return list(found)

    async def add_chunk(
        self,
        capture_id: UUID,
        seq: int,
        storage_key: str,
        speaker_events: JsonValue,
        now: datetime,
    ) -> None:
        self._session.add(
            CaptureChunk(
                capture_session_id=capture_id,
                seq=seq,
                storage_key=storage_key,
                speaker_events=speaker_events,
                received_at=now,
            )
        )
        await self._session.execute(
            update(CaptureSession)
            .where(CaptureSession.capture_session_id == capture_id)
            .values(
                last_chunk_seq=func.greatest(
                    func.coalesce(CaptureSession.last_chunk_seq, seq), seq
                ),
                last_chunk_at=now,
            )
        )
        await self._session.flush()

    async def close(
        self, capture_id: UUID, status: CaptureStatus, last_seq: int, now: datetime
    ) -> None:
        await self._session.execute(
            update(CaptureSession)
            .where(CaptureSession.capture_session_id == capture_id)
            .values(status=status, last_chunk_seq=last_seq, closed_at=now)
        )
