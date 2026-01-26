"""Application configuration - merged from poundcake and poundcake-api."""

import os
from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml
from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application settings loaded from environment variables.

    Merged configuration from both poundcake-api (database/Celery) and
    poundcake (StackStorm/Prometheus/Git/Auth) configurations.
    """

    model_config = SettingsConfigDict(
        env_prefix="POUNDCAKE_",
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # ==========================================================================
    # Application Settings
    # ==========================================================================
    app_name: str = "PoundCake"
    app_version: str = "0.0.1"
    debug: bool = False

    # API Server
    # Note: Using server_host/server_port to avoid collision with Kubernetes
    # auto-generated service environment variables (POUNDCAKE_PORT, etc.)
    server_host: str = "0.0.0.0"
    server_port: int = 8000
    workers: int = 4

    # ==========================================================================
    # Database Settings (from poundcake-api)
    # ==========================================================================
    database_url: str = "mysql+pymysql://poundcake:poundcake@localhost:3306/poundcake"
    database_echo: bool = False

    # ==========================================================================
    # Redis Settings
    # ==========================================================================
    redis_url: str = "redis://localhost:6379/0"
    redis_password: str = ""
    alert_ttl_hours: int = 24  # How long to keep resolved alerts
    lock_timeout_seconds: int = 300  # Distributed lock timeout

    # ==========================================================================
    # Celery Settings (from poundcake-api)
    # ==========================================================================
    celery_broker_url: str = "redis://localhost:6379/1"
    celery_result_backend: str = "redis://localhost:6379/2"
    celery_task_track_started: bool = True
    celery_task_time_limit: int = 300  # 5 minutes
    celery_worker_prefetch_multiplier: int = 4
    celery_worker_max_tasks_per_child: int = 1000

    # ==========================================================================
    # StackStorm Settings (from poundcake)
    # ==========================================================================
    stackstorm_url: str = "https://localhost"
    stackstorm_auth_url: str = ""  # If empty, defaults to stackstorm_url
    stackstorm_api_key: str = ""
    stackstorm_auth_token: str = ""
    stackstorm_verify_ssl: bool = True

    # ==========================================================================
    # Prometheus Settings (from poundcake)
    # ==========================================================================
    prometheus_url: str = "http://localhost:9090"
    prometheus_verify_ssl: bool = True
    prometheus_reload_enabled: bool = False  # Enable Prometheus config reload
    prometheus_reload_url: str = ""  # Custom reload URL

    # Prometheus Operator CRD settings (Kubernetes)
    prometheus_use_crds: bool = True  # Use PrometheusRule CRDs
    prometheus_crd_namespace: str = "monitoring"  # Namespace for PrometheusRule CRDs
    prometheus_crd_labels: dict[str, str] = Field(default_factory=dict)

    # ==========================================================================
    # Git Repository Settings (from poundcake)
    # ==========================================================================
    git_enabled: bool = False
    git_repo_url: str = ""  # Git repo URL (https:// or git@)
    git_branch: str = "main"  # Branch to create PRs against
    git_rules_path: str = "prometheus/rules"  # Path to rules directory in repo
    git_file_per_alert: bool = True  # Create separate file for each alert
    git_file_pattern: str = "{alert_name}.yaml"  # Pattern for alert files
    git_token: str = ""  # Git token for HTTPS auth
    git_ssh_key_path: str = ""  # Path to SSH key for git@ URLs
    git_user_name: str = "PoundCake"  # Git commit author name
    git_user_email: str = "poundcake@localhost"  # Git commit author email
    git_provider: str = "github"  # github, gitlab, gitea, or none

    # ==========================================================================
    # Mappings Settings
    # ==========================================================================
    mappings_path: Path = Field(default=Path("config/mappings"))
    default_timeout: int = 300
    max_concurrent_remediations: int = 10

    # ==========================================================================
    # Logging Settings
    # ==========================================================================
    log_level: str = "INFO"
    log_format: str = "json"  # json or console

    # ==========================================================================
    # Metrics Settings (from poundcake)
    # ==========================================================================
    metrics_enabled: bool = True
    metrics_path: str = "/metrics"

    # ==========================================================================
    # CORS Settings (from poundcake-api)
    # ==========================================================================
    cors_origins: list[str] = ["*"]
    cors_allow_credentials: bool = True
    cors_allow_methods: list[str] = ["*"]
    cors_allow_headers: list[str] = ["*"]

    # ==========================================================================
    # Instance Identification
    # ==========================================================================
    instance_id: str = Field(default_factory=lambda: os.getenv("HOSTNAME", "poundcake-0"))

    # ==========================================================================
    # Authentication Settings (from poundcake)
    # ==========================================================================
    auth_enabled: bool = False
    auth_secret_name: str = "poundcake-admin"  # Kubernetes secret name
    auth_secret_namespace: str = "poundcake"  # Namespace for auth secret
    auth_session_timeout: int = 86400  # Session timeout (24 hours)
    auth_secret_key: str = Field(
        default_factory=lambda: os.urandom(32).hex()
    )  # Secret key for session signing

    # Development/local auth fallback (only used if K8s secret fails)
    auth_dev_username: str = ""  # For local dev only
    auth_dev_password: str = ""  # For local dev only


# Global settings instance
settings = Settings()


@lru_cache
def get_settings() -> Settings:
    """Get cached application settings."""
    return Settings()


def load_yaml_config(path: Path) -> dict[str, Any]:
    """Load a YAML configuration file."""
    with open(path) as f:
        return yaml.safe_load(f) or {}


def load_all_mappings(mappings_path: Path) -> dict[str, Any]:
    """Load all YAML mapping files from the mappings directory.

    This is kept for backwards compatibility with file-based mappings.
    The primary storage is now database-backed.
    """
    mappings: dict[str, Any] = {}

    if not mappings_path.exists():
        return mappings

    for yaml_file in mappings_path.glob("*.yaml"):
        file_mappings = load_yaml_config(yaml_file)
        if "alerts" in file_mappings:
            for alert_name, config in file_mappings["alerts"].items():
                mappings[alert_name] = config

    for yml_file in mappings_path.glob("*.yml"):
        file_mappings = load_yaml_config(yml_file)
        if "alerts" in file_mappings:
            for alert_name, config in file_mappings["alerts"].items():
                mappings[alert_name] = config

    return mappings
