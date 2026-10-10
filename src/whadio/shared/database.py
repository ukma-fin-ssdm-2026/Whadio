from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from enum import StrEnum
from typing import ClassVar

import psycopg
from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict
from sqlalchemy import URL, Engine, MetaData, create_engine, pool
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    metadata: ClassVar[MetaData] = MetaData(
        naming_convention={
            "ix": "ix_%(table_name)s_%(column_0_name)s",
            "uq": "uq_%(table_name)s_%(column_0_N_name)s",
            "ck": "ck_%(table_name)s_%(constraint_name)s",
            "fk": "fk_%(table_name)s_%(column_0_N_name)s_%(referred_table_name)s",
            "pk": "pk_%(table_name)s",
        },
    )


def enum_values(enum_type: type[StrEnum]) -> list[str]:
    return [member.value for member in enum_type]


class ConnectionSettings(BaseSettings):
    model_config: ClassVar[SettingsConfigDict] = SettingsConfigDict(
        env_prefix="WHADIO_DB_", env_file=".env", extra="ignore"
    )

    host: str = Field(default="localhost", description="PostgreSQL hostname.")
    port: int = Field(default=5432, ge=1, le=65535, description="PostgreSQL TCP port.")
    name: str = Field(default="whadio", description="PostgreSQL database name.")


class DatabaseSettings(ConnectionSettings):
    app_password: SecretStr = Field(description="Password for the whadio_app role.")

    def application_url(self) -> URL:
        return URL.create(
            "postgresql+psycopg",
            username="whadio_app",
            password=self.app_password.get_secret_value(),
            host=self.host,
            port=self.port,
            database=self.name,
        )


class MigrationSettings(ConnectionSettings):
    owner_password: SecretStr = Field(description="Password for the whadio_owner migration role.")

    def migration_url(self) -> URL:
        return URL.create(
            "postgresql+psycopg",
            username="whadio_owner",
            password=self.owner_password.get_secret_value(),
            host=self.host,
            port=self.port,
            database=self.name,
        )


class Database:
    def __init__(self, settings: DatabaseSettings) -> None:
        self.engine: AsyncEngine = create_async_engine(
            settings.application_url(),
            pool_pre_ping=True,
            hide_parameters=True,
            connect_args={"connect_timeout": 10},
        )
        self.sessions: async_sessionmaker[AsyncSession] = async_sessionmaker(
            self.engine, expire_on_commit=False
        )

    @asynccontextmanager
    async def transaction(self) -> AsyncGenerator[AsyncSession]:
        """Share this session with every repository, including Audit, in one use case."""
        async with self.sessions.begin() as session:
            yield session

    async def close(self) -> None:
        await self.engine.dispose()


def create_migration_engine(settings: MigrationSettings) -> Engine:
    return create_engine(
        settings.migration_url(),
        module=psycopg,
        poolclass=pool.NullPool,
        hide_parameters=True,
        connect_args={"connect_timeout": 10},
    )
