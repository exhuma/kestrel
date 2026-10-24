"""ORM table definitions for kestrel."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, MetaData, Text
from sqlalchemy.orm import (
    DeclarativeBase,
    Mapped,
    mapped_column,
)


class Base(DeclarativeBase):
    """Declarative base for all kestrel tables.

    The naming convention gives every constraint a predictable name, so a
    migration can refer to it.
    """

    metadata = MetaData(
        naming_convention={
            "pk": "pk_%(table_name)s",
            "fk": "fk_%(table_name)s_%(column_0_name)s",
            "uq": "uq_%(table_name)s_%(column_0_name)s",
            "ix": "ix_%(table_name)s_%(column_0_name)s",
        }
    )


def deferred_fk(target: str) -> ForeignKey:
    """A foreign key to *target* (``table.column``), checked at commit.

    The unit of work orders one flush's inserts by mapper name, not by
    foreign key, so a parent and its child added in the same transaction
    may reach the database child first. A deferred check still rejects a
    dangling reference, at commit.
    """
    return ForeignKey(target, deferrable=True, initially="DEFERRED")


class SessionRow(Base):
    """One dispatched claude session."""

    __tablename__ = "session"

    session_id: Mapped[str] = mapped_column(primary_key=True)
    cwd: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column()
    created_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


class EventRow(Base):
    """One parsed stream-json event belonging to a session."""

    __tablename__ = "event"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    session_id: Mapped[str] = mapped_column(deferred_fk("session.session_id"))
    type: Mapped[str] = mapped_column()
    raw: Mapped[str] = mapped_column(Text)


class WebhookDeliveryRow(Base):
    """One processed GitHub webhook delivery (dedup / at-most-once).

    Keyed by GitHub's ``X-GitHub-Delivery`` id; retention-bounded by
    pruning old rows on insert (feature 002, FR-004/FR-008).
    """

    __tablename__ = "webhook_delivery"

    delivery_id: Mapped[str] = mapped_column(primary_key=True)
    event: Mapped[str] = mapped_column()
    outcome: Mapped[str] = mapped_column()
    repo: Mapped[str | None] = mapped_column(nullable=True)
    issue_number: Mapped[int | None] = mapped_column(nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime)


class IssueDismissalRow(Base):
    """A durable tombstone that a ticket's run was rejected/abandoned.

    Suppresses re-ingestion/reconciliation for a ``task_ref`` until the
    ticket stops qualifying (GitHub: trigger label removed; Jira: the RFC
    leaves the qualifying JQL). Source-neutral key (feature 003, FR-033;
    generalized from the feature-002 ``(repo, issue_number)`` composite).
    """

    __tablename__ = "issue_dismissal"

    task_ref: Mapped[str] = mapped_column(primary_key=True)
    created_at: Mapped[datetime] = mapped_column(DateTime)
