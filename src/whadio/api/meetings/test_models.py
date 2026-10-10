from datetime import UTC, datetime
from uuid import uuid4

from anyio.from_thread import BlockingPortal
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from .fixtures import DESIGN_SYNC_MEETING_ID
from .models import Speaker, Transcript, TranscriptRevision, TranscriptSegment
from .schemas import RevisionType


# Design sync is still queued, so it has no transcript yet.
def test_a_transcript_with_its_first_revision_is_stored_in_one_commit(
    sessionmaker: async_sessionmaker[AsyncSession],
    portal: BlockingPortal,
) -> None:
    async def store_and_read() -> list[tuple[str, str, float]]:
        async with sessionmaker() as db:
            now = datetime.now(UTC)
            transcript_id, revision_id, speaker_id = uuid4(), uuid4(), uuid4()
            db.add_all(
                [
                    Transcript(
                        transcript_id=transcript_id,
                        meeting_id=DESIGN_SYNC_MEETING_ID,
                        language="uk",
                        model_name="parakeet-tdt-0.6b-v3",
                        created_at=now,
                        current_revision_id=revision_id,
                    ),
                    TranscriptRevision(
                        revision_id=revision_id,
                        transcript_id=transcript_id,
                        revision_type=RevisionType.ORIGINAL,
                        created_at=now,
                    ),
                    Speaker(speaker_id=speaker_id, revision_id=revision_id, display_name="Alice"),
                    TranscriptSegment(
                        revision_id=revision_id,
                        speaker_id=speaker_id,
                        start_time_seconds=0.0,
                        end_time_seconds=4.2,
                        text="Let's start the review.",
                    ),
                ]
            )
            await db.commit()

            rows = await db.execute(
                select(
                    Speaker.display_name, TranscriptSegment.text, TranscriptSegment.end_time_seconds
                )
                .join(Speaker, Speaker.speaker_id == TranscriptSegment.speaker_id)
                .join(Transcript, Transcript.current_revision_id == TranscriptSegment.revision_id)
                .where(Transcript.meeting_id == DESIGN_SYNC_MEETING_ID)
            )
            return [(name, text, end) for name, text, end in rows]

    assert portal.call(store_and_read) == [("Alice", "Let's start the review.", 4.2)]
