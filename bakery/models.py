#!/usr/bin/env python3
"""Database models for Bakery."""

from datetime import datetime, timezone
from typing import Any

from sqlalchemy import Boolean, DateTime, JSON, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from bakery.database import Base


class Message(Base):
    """Message queue table for responses from ticketing systems."""

    __tablename__ = "messages"

    id: Mapped[int] = mapped_column(primary_key=True, index=True, autoincrement=True)
    correlation_id: Mapped[str] = mapped_column(
        String(255), nullable=False, index=True, comment="Links to original request"
    )
    ticket_id: Mapped[str | None] = mapped_column(
        String(255),
        nullable=True,
        index=True,
        comment="Bakery internal ticket UUID exposed to PoundCake API",
    )
    mixer_type: Mapped[str] = mapped_column(
        String(50),
        nullable=False,
        comment="servicenow, jira, github, pagerduty, rackspace_core",
    )
    status: Mapped[str] = mapped_column(
        String(50),
        nullable=False,
        default="pending",
        comment="pending, success, error",
    )
    response_data: Mapped[dict[str, Any] | None] = mapped_column(
        JSON, nullable=True, comment="Full response from mixer"
    )
    error_message: Mapped[str | None] = mapped_column(
        Text, nullable=True, comment="Error details if failed"
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime,
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
        comment="When message was created",
    )
    retrieved_at: Mapped[datetime | None] = mapped_column(
        DateTime, nullable=True, comment="When message was retrieved by API"
    )


class TicketRequest(Base):
    """Log of all ticket requests processed by Bakery."""

    __tablename__ = "ticket_requests"

    id: Mapped[int] = mapped_column(primary_key=True, index=True, autoincrement=True)
    correlation_id: Mapped[str] = mapped_column(
        String(255), nullable=False, index=True, comment="Unique request identifier"
    )
    mixer_type: Mapped[str] = mapped_column(
        String(50),
        nullable=False,
        comment="servicenow, jira, github, pagerduty, rackspace_core",
    )
    action: Mapped[str] = mapped_column(
        String(50), nullable=False, comment="create, update, close, comment, etc"
    )
    request_data: Mapped[dict[str, Any]] = mapped_column(
        JSON, nullable=False, comment="Original request payload"
    )
    ticket_id: Mapped[str | None] = mapped_column(
        String(255), nullable=True, comment="Bakery internal ticket UUID if mapped"
    )
    status: Mapped[str] = mapped_column(
        String(50),
        nullable=False,
        default="pending",
        comment="pending, processing, success, error",
    )
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime,
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
        index=True,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime,
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )
    completed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


class MixerConfig(Base):
    """Optional table for storing mixer-specific configuration."""

    __tablename__ = "mixer_configs"

    id: Mapped[int] = mapped_column(primary_key=True, index=True, autoincrement=True)
    mixer_type: Mapped[str] = mapped_column(
        String(50), nullable=False, unique=True, comment="Mixer identifier"
    )
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    config_data: Mapped[dict[str, Any] | None] = mapped_column(
        JSON, nullable=True, comment="Mixer-specific settings"
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, default=lambda: datetime.now(timezone.utc)
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime,
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )


class TicketIdMapping(Base):
    """Stable ID mapping between Bakery internal UUIDs and external ticket IDs."""

    __tablename__ = "ticket_id_mappings"
    __table_args__ = (
        UniqueConstraint("internal_ticket_id", name="uq_ticket_id_mappings_internal_ticket_id"),
    )

    id: Mapped[int] = mapped_column(primary_key=True, index=True, autoincrement=True)
    internal_ticket_id: Mapped[str] = mapped_column(
        String(36),
        nullable=False,
        index=True,
        comment="Bakery-generated UUID exposed to PoundCake API",
    )
    mixer_type: Mapped[str] = mapped_column(
        String(50),
        nullable=False,
        index=True,
        comment="servicenow, jira, github, pagerduty, rackspace_core",
    )
    external_ticket_id: Mapped[str] = mapped_column(
        String(255),
        nullable=False,
        index=True,
        comment="Native ticket/incident/issue ID from external system",
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime,
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
        comment="When mapping was created",
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime,
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
        comment="When mapping was last updated",
    )
