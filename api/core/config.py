#  ___                        _  ____      _
# |  _ \ ___  _   _ _ __   __| |/ ___|__ _| | _____
# | |_) / _ \| | | | '_ \ / _` | |   / _` | |/ / _ \
# |  __/ (_) | |_| | | | | (_| | |__| (_| |   <  __/
# |_|   \___/ \__,_|_| |_|\__,_|\____\__,_|_|\_\___|
#
"""Application configuration - merged from poundcake and poundcake-api."""

import os
from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml
from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application settings loaded from environment variables."""

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
    app_version: str = "1.0.0"
    debug: bool = False

    # API Server
    server_host: str = "0.0.0.0"
    server_port: int = 8000
    workers: int = 4

    # ==========================================================================
    # Database Settings
    # ==========================================================================
    # Pointing to the 'mariadb' service in docker-compose
    database_url: str = "mysql+pymysql://poundcake:poundcake@mariadb:3306/poundcake"
    database_echo: bool = False

    # ==========================================================================
    # Redis & Celery Settings
    # ==========================================================================
    # Pointing to the 'redis' service in docker-compose
    redis_url: str = "redis://redis:6379/0"
    redis_password: str = ""
    alert_ttl_hours: int = 24
    lock_timeout_seconds: int = 300

    celery_broker_url: str = "redis://redis:6379/1"
    celery_result_backend: str = "redis://redis:6379/2"
    celery_task_track_started: bool = True
    celery_task_time_limit: int = 300
    celery_worker_prefetch_multiplier: int = 4
    celery_worker_max_tasks_per_child: int = 1000

    # ==========================================================================
    # StackStorm Settings
    # ==========================================================================
    stackstorm_url: str = "https://st2web"  # Matches st2 service name
    stackstorm_auth_url: str = ""
    stackstorm_api_key: str = ""
    stackstorm_auth_token: str = ""
    stackstorm_verify_ssl: bool = False

    def get_stackstorm_api_key(self) -> str:
        """Get StackStorm API key from env var or runtime config file.

        Priority:
        1. Environment variable (POUNDCAKE_STACKSTORM_API_KEY)
        2. Runtime config file (/app/config/st2_api_key)
        3. Empty string
        """
        # First check environment variable
        if self.stackstorm_api_key:
            return self.stackstorm_api_key

        # Fall back to runtime config file (written by setup container)
        config_file = Path("/app/config/st2_api_key")
        if config_file.exists():
            try:
                key = config_file.read_text().strip()
                if key:
                    return key
            except Exception:
                pass

        return ""

    # ==========================================================================
    # Prometheus Settings
    # ==========================================================================
    prometheus_url: str = "http://prometheus:9090"
    prometheus_verify_ssl: bool = True
    prometheus_reload_enabled: bool = True
    prometheus_reload_url: str = ""

    # Prometheus Operator CRD settings (Kubernetes)
    prometheus_use_crds: bool = True
    prometheus_crd_namespace: str = "monitoring"
    prometheus_crd_labels: dict[str, str] = Field(default_factory=dict)

    # ==========================================================================
    # Git Repository Settings
    # ==========================================================================
    git_enabled: bool = False
    git_repo_url: str = ""
    git_branch: str = "main"
    git_rules_path: str = "prometheus/rules"
    git_file_per_alert: bool = True
    git_file_pattern: str = "{alert_name}.yaml"
    git_token: str = ""
    git_ssh_key_path: str = ""
    git_user_name: str = "PoundCake"
    git_user_email: str = "poundcake@localhost"
    git_provider: str = "github"

    # ==========================================================================
    # Mappings & Logging
    # ==========================================================================
    mappings_path: Path = Field(default=Path("config/mappings"))
    default_timeout: int = 300
    max_concurrent_remediations: int = 10

    log_level: str = "INFO"
    log_format: str = "console"  # Change to 'json' for production/Helm

    # ==========================================================================
    # Metrics & CORS
    # ==========================================================================
    metrics_enabled: bool = True
    metrics_path: str = "/metrics"

    cors_origins: list[str] = ["*"]
    allowed_origins: list[str] = ["*"]  # Alias for main.py compatibility
    cors_allow_credentials: bool = True
    cors_allow_methods: list[str] = ["*"]
    cors_allow_headers: list[str] = ["*"]

    # ==========================================================================
    # Authentication & Identification
    # ==========================================================================
    instance_id: str = Field(default_factory=lambda: os.getenv("HOSTNAME", "poundcake-0"))

    auth_enabled: bool = True
    auth_secret_name: str = "poundcake-admin"
    auth_secret_namespace: str = "poundcake"
    auth_session_timeout: int = 86400
    auth_secret_key: str = Field(default_factory=lambda: os.urandom(32).hex())

    # Development/local auth fallback
    auth_dev_username: str = "admin"
    auth_dev_password: str = "chained-to-the-oven"


settings = Settings()


@lru_cache
def get_settings() -> Settings:
    return Settings()


def load_yaml_config(path: Path) -> dict[str, Any]:
    with open(path) as f:
        return yaml.safe_load(f) or {}


def load_all_mappings(mappings_path: Path) -> dict[str, Any]:
    mappings: dict[str, Any] = {}
    if not mappings_path.exists():
        return mappings
    for pattern in ["*.yaml", "*.yml"]:
        for yaml_file in mappings_path.glob(pattern):
            file_mappings = load_yaml_config(yaml_file)
            if "alerts" in file_mappings:
                for alert_name, config in file_mappings["alerts"].items():
                    mappings[alert_name] = config
    return mappings
