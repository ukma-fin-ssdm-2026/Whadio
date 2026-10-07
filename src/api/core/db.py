import os
from collections.abc import AsyncGenerator
from typing import Annotated, Final

from fastapi import Depends, Request
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase

# SQLite until the team runs PostgreSQL; switching is a matter of this URL
# (e.g. postgresql+asyncpg://user:password@host/whadio) and installing its driver.
DEFAULT_DATABASE_URL: Final = "sqlite+aiosqlite:///./whadio.db"


class Base(DeclarativeBase):
    pass


def database_url() -> str:
    return os.environ.get("WHADIO_DATABASE_URL", DEFAULT_DATABASE_URL)


async def create_tables(engine: AsyncEngine) -> None:
    # Importing the models registers their tables on Base.metadata.
    from ..accounts import models  # noqa: F401

    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)


async def _db(request: Request) -> AsyncGenerator[AsyncSession]:
    sessionmaker: async_sessionmaker[AsyncSession] = request.app.state.sessionmaker
    async with sessionmaker() as session:
        yield session


Db = Annotated[AsyncSession, Depends(_db)]
