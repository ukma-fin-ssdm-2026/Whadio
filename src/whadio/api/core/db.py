from datetime import UTC, datetime
from typing import Annotated, Final, final, override

from fastapi import Depends
from sqlalchemy import DateTime, TypeDecorator
from sqlalchemy.engine import Dialect
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker
from sqlalchemy.orm import DeclarativeBase

# SQLite until the team runs PostgreSQL; switching is a matter of this URL
# (e.g. postgresql+asyncpg://user:password@host/whadio) and installing its driver.
DEFAULT_DATABASE_URL: Final = "sqlite+aiosqlite:///./whadio.db"


class Base(DeclarativeBase):
    pass


class SessionFactory(async_sessionmaker[AsyncSession]):
    """Opens the app's database sessions and keeps the engine they run on."""

    def __init__(self, engine: AsyncEngine) -> None:
        super().__init__(engine, expire_on_commit=False)
        self.engine: Final = engine


@final
class UtcDateTime(TypeDecorator[datetime]):
    """Timezone-aware UTC datetimes, also on SQLite, which stores them without an offset."""

    impl = DateTime(timezone=True)
    cache_ok = True

    @override
    def process_bind_param(self, value: datetime | None, dialect: Dialect) -> datetime | None:
        return None if value is None else value.astimezone(UTC)

    @override
    def process_result_value(self, value: datetime | None, dialect: Dialect) -> datetime | None:
        if value is None:
            return None
        return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


async def create_tables(engine: AsyncEngine) -> None:
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)


def get_session() -> AsyncSession:
    raise NotImplementedError("create_app() supplies the session")


Db = Annotated[AsyncSession, Depends(get_session)]
