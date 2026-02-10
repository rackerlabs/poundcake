#!/usr/bin/env python3
"""Database models for Bakery."""

from datetime import datetime, timezone
from sqlalchemy import Column, Integer, String, Text, DateTime, Boolean, JSON
from bakery.database import Base


class Message(Base):
    """
    Message queue table for responses from ticketing systems.

    PoundCake API polls this table to retrieve responses.
    """

    __tablename__ = "messages"

    id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    correlation_id = Column(
        String(255), nullable=False, index=True, comment="Links to original request"
    )
    ticket_id = Column(
        String(255), nullable=True, index=True, comment="Ticket ID from external system"
    )
    mixer_type = Column(
        String(50),
        nullable=False,
        comment="servicenow, jira, github, pagerduty, rackspace_core",
    )
    status = Column(
        String(50),
        nullable=False,
        default="pending",
        comment="pending, success, error",
    )
    response_data = Column(JSON, nullable=True, comment="Full response from mixer")
    error_message = Column(Text, nullable=True, comment="Error details if failed")
    created_at = Column(
        DateTime,
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
        comment="When message was created",
    )
    retrieved_at = Column(DateTime, nullable=True, comment="When message was retrieved by API")


class TicketRequest(Base):
    """
    Log of all ticket requests processed by Bakery.

    Provides audit trail and debugging capability.
    """

    __tablename__ = "ticket_requests"

    id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    correlation_id = Column(
        String(255), nullable=False, index=True, comment="Unique request identifier"
    )
    mixer_type = Column(
        String(50),
        nullable=False,
        comment="servicenow, jira, github, pagerduty, rackspace_core",
    )
    action = Column(String(50), nullable=False, comment="create, update, close, comment, etc")
    request_data = Column(JSON, nullable=False, comment="Original request payload")
    ticket_id = Column(String(255), nullable=True, comment="Ticket ID if successfully created")
    status = Column(
        String(50),
        nullable=False,
        default="pending",
        comment="pending, processing, success, error",
    )
    error_message = Column(Text, nullable=True)
    created_at = Column(
        DateTime,
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
        index=True,
    )
    updated_at = Column(
        DateTime,
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )
    completed_at = Column(DateTime, nullable=True)


class MixerConfig(Base):
    """
    Optional table for storing mixer-specific configuration.

    Can be used for per-mixer settings that need to be dynamic.
    """

    __tablename__ = "mixer_configs"

    id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    mixer_type = Column(String(50), nullable=False, unique=True, comment="Mixer identifier")
    enabled = Column(Boolean, nullable=False, default=True)
    config_data = Column(JSON, nullable=True, comment="Mixer-specific settings")
    created_at = Column(DateTime, nullable=False, default=lambda: datetime.now(timezone.utc))
    updated_at = Column(
        DateTime,
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )
