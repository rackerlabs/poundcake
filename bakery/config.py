#!/usr/bin/env python3
"""Bakery configuration settings."""

import os
from typing import Optional


def _env_to_bool(value: Optional[str], default: bool = False) -> bool:
    """Parse a boolean-like environment variable string."""
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


class Settings:
    """Bakery application settings loaded from environment variables."""

    def __init__(self) -> None:
        """Initialize settings from environment variables."""
        # Application
        self.environment: str = os.getenv("ENVIRONMENT", "production")
        self.log_level: str = os.getenv("LOG_LEVEL", "INFO")
        self.api_prefix: str = "/api/v1"

        # Database
        self.database_host: str = os.getenv("DATABASE_HOST", "bakery-mariadb")
        self.database_port: int = int(os.getenv("DATABASE_PORT", "3306"))
        self.database_user: str = os.getenv("DATABASE_USER", "bakery")
        self.database_password: str = os.getenv("DATABASE_PASSWORD", "")
        self.database_name: str = os.getenv("DATABASE_NAME", "bakery")

        # Message queue settings
        self.message_retention_hours: int = int(os.getenv("MESSAGE_RETENTION_HOURS", "24"))
        self.max_messages_per_poll: int = int(os.getenv("MAX_MESSAGES_PER_POLL", "100"))

        # Mixer settings
        self.mixer_timeout_sec: int = int(os.getenv("MIXER_TIMEOUT_SEC", "30"))
        self.mixer_max_retries: int = int(os.getenv("MIXER_MAX_RETRIES", "3"))
        self.ticketing_dry_run: bool = _env_to_bool(os.getenv("TICKETING_DRY_RUN"), default=False)

        # ServiceNow
        self.servicenow_url: Optional[str] = os.getenv("SERVICENOW_URL")
        self.servicenow_username: Optional[str] = os.getenv("SERVICENOW_USERNAME")
        self.servicenow_password: Optional[str] = os.getenv("SERVICENOW_PASSWORD")

        # Jira
        self.jira_url: Optional[str] = os.getenv("JIRA_URL")
        self.jira_username: Optional[str] = os.getenv("JIRA_USERNAME")
        self.jira_api_token: Optional[str] = os.getenv("JIRA_API_TOKEN")

        # GitHub
        self.github_token: Optional[str] = os.getenv("GITHUB_TOKEN")

        # PagerDuty
        self.pagerduty_api_key: Optional[str] = os.getenv("PAGERDUTY_API_KEY")

        # Rackspace Core
        self.rackspace_core_url: Optional[str] = os.getenv(
            "RACKSPACE_CORE_URL", "https://ws.core.rackspace.com"
        )
        self.rackspace_core_username: Optional[str] = os.getenv("RACKSPACE_CORE_USERNAME")
        self.rackspace_core_password: Optional[str] = os.getenv("RACKSPACE_CORE_PASSWORD")

    @property
    def database_url(self) -> str:
        """Construct database URL for SQLAlchemy."""
        return (
            f"mysql+pymysql://{self.database_user}:{self.database_password}"
            f"@{self.database_host}:{self.database_port}/{self.database_name}"
        )


# Global settings instance
settings = Settings()
