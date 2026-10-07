from datetime import UTC, datetime
from uuid import UUID, uuid4

from sqlalchemy import DateTime, ForeignKey, String, TypeDecorator
from sqlalchemy.engine import Dialect
from sqlalchemy.orm import Mapped, mapped_column

from ..core.db import Base
from .schemas import SessionKind, UserRead


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


class User(Base):
    __tablename__ = "users"

    user_id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    # Stored lowercased: addresses are compared case-insensitively everywhere.
    email: Mapped[str] = mapped_column(String(254), unique=True)
    name: Mapped[str] = mapped_column(String(100))
    password_hash: Mapped[str] = mapped_column(String(64))
    is_administrator: Mapped[bool] = mapped_column(default=False)
    terms_accepted_at: Mapped[datetime] = mapped_column(UtcDateTime)
    created_at: Mapped[datetime] = mapped_column(UtcDateTime)

    def to_read(self) -> UserRead:
        return UserRead(
            id=self.user_id,
            email=self.email,
            name=self.name,
            is_administrator=self.is_administrator,
            created_at=self.created_at,
        )


class UserSession(Base):
    __tablename__ = "sessions"

    session_id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    user_id: Mapped[UUID] = mapped_column(ForeignKey("users.user_id", ondelete="CASCADE"))
    kind: Mapped[SessionKind]
    token_hash: Mapped[str] = mapped_column(String(64), unique=True)
    created_at: Mapped[datetime] = mapped_column(UtcDateTime)
    expires_at: Mapped[datetime] = mapped_column(UtcDateTime)
