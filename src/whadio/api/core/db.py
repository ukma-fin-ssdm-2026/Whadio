from collections.abc import AsyncGenerator
from datetime import UTC, datetime
from typing import Annotated, Final

from fastapi import Depends, Request
from sqlalchemy import DateTime, TypeDecorator
from sqlalchemy.engine import Dialect
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker
from sqlalchemy.orm import DeclarativeBase

# SQLite until the team runs PostgreSQL; switching is a matter of this URL
# (e.g. postgresql+asyncpg://user:password@host/whadio) and installing its driver.
DEFAULT_DATABASE_URL: Final = "sqlite+aiosqlite:///./whadio.db"


class Base(DeclarativeBase):
    pass


class UtcDateTime(TypeDecorator[datetime]):
    """Timezone-aware UTC datetimes, also on SQLite, which stores them without an offset."""

    impl = DateTime(timezone=True)
    cache_ok = True

    def process_bind_param(self, value: datetime | None, dialect: Dialect) -> datetime | None:
        return None if value is None else value.astimezone(UTC)

    def process_result_value(self, value: datetime | None, dialect: Dialect) -> datetime | None:
        if value is None:
            return None
        return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


async def create_tables(engine: AsyncEngine) -> None:
    # Importing the models registers their tables on Base.metadata.
    from ..accounts import models  # noqa: F401
    from ..audit import models as audit_models  # noqa: F401
    from ..meetings import models as meeting_models  # noqa: F401

    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)


async def _db(request: Request) -> AsyncGenerator[AsyncSession]:
    sessionmaker: async_sessionmaker[AsyncSession] = request.app.state.sessionmaker
    async with sessionmaker() as session:
        yield session


Db = Annotated[AsyncSession, Depends(_db)]
