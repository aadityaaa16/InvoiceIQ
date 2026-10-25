"""Declarative base and shared column helpers for all SQLAlchemy models."""

import enum
import uuid
from datetime import datetime

from sqlalchemy import DateTime, Enum, MetaData, func
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

# Deterministic constraint names. Without this, Postgres auto-generates names and
# Alembic cannot reliably find constraints later to alter or drop them.
NAMING_CONVENTION = {
    "ix": "ix_%(column_0_label)s",
    "uq": "uq_%(table_name)s_%(column_0_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}


class Base(DeclarativeBase):
    metadata = MetaData(naming_convention=NAMING_CONVENTION)


class UUIDPrimaryKeyMixin:
    """UUID ids: not guessable (no /invoices/124 probing) and can be generated in Python."""

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)


class CreatedAtMixin:
    # server_default: the database fills the value, so it is correct even for rows
    # inserted outside the ORM. timezone=True stores TIMESTAMPTZ (always UTC-aware).
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


def enum_column(enum_cls: type[enum.Enum], name: str) -> Enum:
    """Store a Python enum as VARCHAR + CHECK constraint instead of a native Postgres ENUM.

    Native ENUM types need special migrations to add values and cannot drop values at all.
    A CHECK constraint still rejects invalid values but is trivial to change in a migration.
    values_callable stores the enum's value ("needs_review"), not its name ("NEEDS_REVIEW").
    """
    return Enum(
        enum_cls,
        name=name,
        native_enum=False,
        create_constraint=True,
        length=20,
        values_callable=lambda members: [member.value for member in members],
        validate_strings=True,
    )
