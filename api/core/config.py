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
from urllib.parse import quote
import yaml
from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

from api.version import __version__


def _default_redis_url() -> str:
    host = os.getenv("REDIS_HOST", "poundcake-redis").strip() or "poundcake-redis"
    port = os.getenv("REDIS_PORT", "6379").strip() or "6379"
    db = os.getenv("REDIS_DB", "0").strip() or "0"
    password = os.getenv("REDIS_PASSWORD", "").strip()
    auth = f":{quote(password)}@" if password else ""
    return f"redis://{auth}{host}:{port}/{db}"


def _default_bakery_monitor_id() -> str:
    explicit = os.getenv("POUNDCAKE_BAKERY_MONITOR_ID", "").strip()
    if explicit:
        return explicit
    namespace = os.getenv("POD_NAMESPACE", "").strip()
    release_name = (
        os.getenv("POUNDCAKE_BAKERY_MONITOR_RELEASE_NAME", "").strip()
        or os.getenv("HELM_RELEASE_NAME", "").strip()
        or os.getenv("RELEASE_NAME", "").strip()
    )
    if namespace and release_name:
        return f"{namespace}/{release_name}"
    return ""


def _default_bakery_monitor_namespace() -> str:
    return (
        os.getenv("POUNDCAKE_BAKERY_MONITOR_NAMESPACE", "").strip()
        or os.getenv("POD_NAMESPACE", "").strip()
    )


def _default_bakery_monitor_release_name() -> str:
    return (
        os.getenv("POUNDCAKE_BAKERY_MONITOR_RELEASE_NAME", "").strip()
        or os.getenv("HELM_RELEASE_NAME", "").strip()
        or os.getenv("RELEASE_NAME", "").strip()
    )


def _default_bakery_monitor_environment_label() -> str:
    explicit = os.getenv("POUNDCAKE_BAKERY_MONITOR_ENVIRONMENT_LABEL", "").strip()
    if explicit:
        return explicit
    namespace = _default_bakery_monitor_namespace()
    release_name = _default_bakery_monitor_release_name()
    if namespace and release_name:
        return f"{namespace}/{release_name}"
    return namespace or release_name or ""


def _default_bakery_monitor_region() -> str:
    return (
        os.getenv("POUNDCAKE_BAKERY_MONITOR_REGION", "").strip()
        or os.getenv("REGION", "").strip()
        or os.getenv("CLOUD_REGION", "").strip()
    )


def _default_bakery_monitor_cluster_name() -> str:
    return (
        os.getenv("POUNDCAKE_BAKERY_MONITOR_CLUSTER_NAME", "").strip()
        or os.getenv("CLUSTER_NAME", "").strip()
        or os.getenv("KUBERNETES_CLUSTER_NAME", "").strip()
    )


def _default_bakery_monitor_tags() -> list[str]:
    raw = os.getenv("POUNDCAKE_BAKERY_MONITOR_TAGS", "").strip()
    if not raw:
        return []
    values = [item.strip() for item in raw.split(",")]
    return [item for item in values if item]


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
    app_version: str = Field(default=__version__)
    debug: bool = False
    testing: bool = Field(
        default_factory=lambda: os.getenv("TESTING", "").strip().lower() in {"1", "true", "yes"}
    )

    # API Server
    server_host: str = "0.0.0.0"
    server_port: int = 8000
    workers: int = 4

    # ==========================================================================
    # Database Settings
    # ==========================================================================
    # Default to in-cluster MariaDB service (overridden by Helm env var in production).
    database_url: str = "mysql+pymysql://poundcake:poundcake@poundcake-mariadb:3306/poundcake"
    database_echo: bool = False

    # ==========================================================================
    # Redis Settings
    # ==========================================================================
    # Default to in-cluster Redis service (overridden by Helm env var in production).
    redis_url: str = Field(default_factory=_default_redis_url)
    redis_password: str = ""
    alert_ttl_hours: int = 24
    lock_timeout_seconds: int = 300

    # ==========================================================================
    # Component Health Check Settings
    # ==========================================================================
    mongodb_enabled: bool = True
    mongodb_external: bool = False
    rabbitmq_enabled: bool = True
    redis_enabled: bool = True

    # ==========================================================================
    # StackStorm Settings
    # ==========================================================================
    stackstorm_url: str = "http://poundcake-st2api:9101"
    stackstorm_auth_url: str = "http://poundcake-st2auth:9100"
    stackstorm_api_key: str = ""
    stackstorm_auth_token: str = ""
    stackstorm_verify_ssl: bool = False
    stackstorm_startup_max_attempts: int = 120
    stackstorm_startup_delay_seconds: float = 2.0
    pack_sync_token: str = ""
    stackstorm_pack_sync_register_retries: int = 30
    stackstorm_pack_sync_register_delay_seconds: float = 2.0

    def get_stackstorm_api_key(self) -> str:
        """Get StackStorm API key from env var or runtime config file.

        Priority:
        1. Environment variable (POUNDCAKE_STACKSTORM_API_KEY)
        2. Runtime config file from ST2_API_KEY_FILE when set
        3. Known runtime config file mount paths
        3. Empty string
        """
        # First check environment variable
        if self.stackstorm_api_key:
            return self.stackstorm_api_key

        # Fall back to runtime config file (written by setup container or mounted secret).
        config_files: list[Path] = []
        explicit_key_file = os.getenv("ST2_API_KEY_FILE", "").strip()
        if explicit_key_file:
            config_files.append(Path(explicit_key_file))
        config_files.extend(
            [
                Path("/run/secrets/st2/st2_api_key"),
                Path("/app/config/st2_api_key"),
                Path("/app/config/st2-apikeys/api-key"),
            ]
        )
        for config_file in config_files:
            if not config_file.exists():
                continue
            try:
                key = config_file.read_text().strip()
                if key:
                    return key
            except Exception:
                continue

        # Fall back to StackStorm legacy YAML secret format if present.
        apikeys_yaml = Path("/app/config/st2-apikeys/apikeys.yaml")
        if apikeys_yaml.exists():
            try:
                data = yaml.safe_load(apikeys_yaml.read_text())
                if isinstance(data, str):
                    key = data.strip()
                    if key and key.lower() != "null":
                        return key
                elif isinstance(data, dict):
                    key = str(data.get("key", "")).strip()
                    if key:
                        return key
                    apikeys = data.get("apikeys")
                    if isinstance(apikeys, list):
                        for item in reversed(apikeys):
                            if isinstance(item, dict):
                                key = str(item.get("key", "")).strip()
                                if key:
                                    return key
                elif isinstance(data, list):
                    for item in reversed(data):
                        if isinstance(item, dict):
                            key = str(item.get("key", "")).strip()
                            if key:
                                return key
            except Exception:
                pass

        return ""

    # ==========================================================================
    # Prometheus Settings
    # ==========================================================================
    prometheus_url: str = (
        "http://kube-prometheus-stack-prometheus.monitoring.svc.cluster.local:9090"
    )
    prometheus_verify_ssl: bool = True
    prometheus_reload_enabled: bool = True
    prometheus_reload_url: str = ""

    # Prometheus Operator CRD settings (Kubernetes)
    prometheus_use_crds: bool = True
    prometheus_crd_namespace: str = "prometheus"
    prometheus_crd_labels: dict[str, str] = Field(default_factory=dict)

    # ==========================================================================
    # Git Repository Settings
    # ==========================================================================
    git_enabled: bool = False
    git_repo_url: str = ""
    git_branch: str = "main"
    git_rules_path: str = "prometheus/rules"
    git_workflows_path: str = "poundcake/workflows"
    git_actions_path: str = "poundcake/actions"
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
    bootstrap_ingredients_dir: str = "/app/bootstrap/ingredients"
    bootstrap_ingredients_file: str = "/app/bootstrap/ingredients/bakery.yaml"
    bootstrap_recipes_dir: str = "/app/bootstrap/recipes"
    bootstrap_remote_sync_enabled: bool = True
    bootstrap_rules_repo_url: str = ""
    bootstrap_rules_branch: str = "main"
    bootstrap_rules_path: str = "alerts"
    default_timeout: int = 300
    max_concurrent_remediations: int = 10
    httpx_timeout_seconds: int = 30
    httpx_connect_timeout_seconds: int = 10
    httpx_read_timeout_seconds: int = 30
    httpx_write_timeout_seconds: int = 30
    httpx_max_connections: int = 100
    httpx_max_keepalive: int = 20
    httpx_retries: int = 2
    httpx_retry_backoff_seconds: float = 0.5
    httpx_retry_statuses: list[int] = Field(default_factory=lambda: [429, 500, 502, 503, 504])
    poller_http_retries: int = 0
    external_http_retries: int = 2
    chef_patch_retries: int = 3
    chef_patch_retry_backoff_seconds: float = 1.0
    chef_execute_missing_workflow_retries: int = 5
    chef_execute_missing_workflow_retry_backoff_seconds: float = 2.0
    chef_missing_execution_timeout_seconds: int = 60
    incident_reconcile_interval_seconds: int = 30
    incident_reconcile_limit: int = 25

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
    auth_secret_namespace: str = Field(
        default_factory=lambda: os.getenv("POD_NAMESPACE", "poundcake")
    )
    auth_session_timeout: int = 86400
    auth_secret_key: str = Field(default_factory=lambda: os.urandom(32).hex())
    auth_oidc_state_ttl: int = 600
    auth_redis_prefix: str = "poundcake:auth"
    auth_rbac_enabled: bool = True
    auth_service_token: str = ""

    # Local bootstrap superuser.
    auth_local_enabled: bool = True
    auth_username: str = ""
    auth_password: str = ""
    auth_dev_username: str = ""
    auth_dev_password: str = ""

    # Active Directory / LDAP.
    auth_ad_enabled: bool = False
    auth_ad_server_uri: str = ""
    auth_ad_bind_dn: str = ""
    auth_ad_bind_password: str = ""
    auth_ad_user_base_dn: str = ""
    auth_ad_user_filter: str = "(&(objectClass=user)(sAMAccountName={username}))"
    auth_ad_group_attribute: str = "memberOf"
    auth_ad_display_name_attribute: str = "displayName"
    auth_ad_username_attribute: str = "sAMAccountName"
    auth_ad_subject_attribute: str = "distinguishedName"
    auth_ad_use_ssl: bool = True
    auth_ad_validate_tls: bool = True
    auth_ad_ca_certs_file: str = ""
    auth_ad_group_name_regex: str = r"CN=([^,]+)"

    # Auth0.
    auth_auth0_enabled: bool = False
    auth_auth0_domain: str = ""
    auth_auth0_audience: str = ""
    auth_auth0_scope: str = "openid profile email"
    auth_auth0_organization: str = ""
    auth_auth0_connection: str = ""
    auth_auth0_username_claim: str = "email"
    auth_auth0_display_name_claim: str = "name"
    auth_auth0_groups_claim: str = "groups"
    auth_auth0_subject_claim: str = "sub"
    auth_auth0_ui_enabled: bool = Field(
        default_factory=lambda: bool(
            os.getenv("POUNDCAKE_AUTH_AUTH0_UI_CLIENT_ID")
            or os.getenv("POUNDCAKE_AUTH_AUTH0_CLIENT_ID")
        )
    )
    auth_auth0_ui_client_id: str = Field(
        default_factory=lambda: os.getenv("POUNDCAKE_AUTH_AUTH0_UI_CLIENT_ID", "")
        or os.getenv("POUNDCAKE_AUTH_AUTH0_CLIENT_ID", "")
    )
    auth_auth0_ui_client_secret: str = Field(
        default_factory=lambda: os.getenv("POUNDCAKE_AUTH_AUTH0_UI_CLIENT_SECRET", "")
        or os.getenv("POUNDCAKE_AUTH_AUTH0_CLIENT_SECRET", "")
    )
    auth_auth0_ui_callback_url: str = Field(
        default_factory=lambda: os.getenv("POUNDCAKE_AUTH_AUTH0_UI_CALLBACK_URL", "")
        or os.getenv("POUNDCAKE_AUTH_AUTH0_CALLBACK_URL", "")
    )
    auth_auth0_cli_enabled: bool = Field(
        default_factory=lambda: bool(
            os.getenv("POUNDCAKE_AUTH_AUTH0_CLI_CLIENT_ID")
            or os.getenv("POUNDCAKE_AUTH_AUTH0_CLIENT_ID")
        )
    )
    auth_auth0_cli_client_id: str = Field(
        default_factory=lambda: os.getenv("POUNDCAKE_AUTH_AUTH0_CLI_CLIENT_ID", "")
        or os.getenv("POUNDCAKE_AUTH_AUTH0_CLIENT_ID", "")
    )
    auth_auth0_cli_client_secret: str = Field(
        default_factory=lambda: os.getenv("POUNDCAKE_AUTH_AUTH0_CLI_CLIENT_SECRET", "")
        or os.getenv("POUNDCAKE_AUTH_AUTH0_CLIENT_SECRET", "")
    )

    # Azure AD / Microsoft Entra ID.
    auth_azure_ad_enabled: bool = False
    auth_azure_ad_tenant: str = ""
    auth_azure_ad_audience: str = ""
    auth_azure_ad_scope: str = "openid profile email"
    auth_azure_ad_username_claim: str = "preferred_username"
    auth_azure_ad_display_name_claim: str = "name"
    auth_azure_ad_groups_claim: str = "groups"
    auth_azure_ad_subject_claim: str = "sub"
    auth_azure_ad_ui_enabled: bool = Field(
        default_factory=lambda: bool(
            os.getenv("POUNDCAKE_AUTH_AZURE_AD_UI_CLIENT_ID")
            or os.getenv("POUNDCAKE_AUTH_AZURE_AD_CLIENT_ID")
        )
    )
    auth_azure_ad_ui_client_id: str = Field(
        default_factory=lambda: os.getenv("POUNDCAKE_AUTH_AZURE_AD_UI_CLIENT_ID", "")
        or os.getenv("POUNDCAKE_AUTH_AZURE_AD_CLIENT_ID", "")
    )
    auth_azure_ad_ui_client_secret: str = Field(
        default_factory=lambda: os.getenv("POUNDCAKE_AUTH_AZURE_AD_UI_CLIENT_SECRET", "")
        or os.getenv("POUNDCAKE_AUTH_AZURE_AD_CLIENT_SECRET", "")
    )
    auth_azure_ad_ui_callback_url: str = Field(
        default_factory=lambda: os.getenv("POUNDCAKE_AUTH_AZURE_AD_UI_CALLBACK_URL", "")
        or os.getenv("POUNDCAKE_AUTH_AZURE_AD_CALLBACK_URL", "")
    )
    auth_azure_ad_cli_enabled: bool = Field(
        default_factory=lambda: bool(
            os.getenv("POUNDCAKE_AUTH_AZURE_AD_CLI_CLIENT_ID")
            or os.getenv("POUNDCAKE_AUTH_AZURE_AD_CLIENT_ID")
        )
    )
    auth_azure_ad_cli_client_id: str = Field(
        default_factory=lambda: os.getenv("POUNDCAKE_AUTH_AZURE_AD_CLI_CLIENT_ID", "")
        or os.getenv("POUNDCAKE_AUTH_AZURE_AD_CLIENT_ID", "")
    )

    # ==========================================================================
    # Bakery Integration Settings
    # ==========================================================================
    bakery_enabled: bool = False
    bakery_base_url: str = ""
    bakery_auth_mode: str = "hmac"
    bakery_hmac_key_id: str = ""
    bakery_hmac_key: str = ""
    bakery_bootstrap_hmac_key_id: str = ""
    bakery_bootstrap_hmac_key: str = ""
    bakery_secret_encryption_key: str = ""
    bakery_monitor_id: str = Field(default_factory=_default_bakery_monitor_id)
    bakery_monitor_environment_label: str = Field(
        default_factory=_default_bakery_monitor_environment_label
    )
    bakery_monitor_region: str = Field(default_factory=_default_bakery_monitor_region)
    bakery_monitor_cluster_name: str = Field(default_factory=_default_bakery_monitor_cluster_name)
    bakery_monitor_namespace: str = Field(default_factory=_default_bakery_monitor_namespace)
    bakery_monitor_release_name: str = Field(default_factory=_default_bakery_monitor_release_name)
    bakery_monitor_tags: list[str] = Field(default_factory=_default_bakery_monitor_tags)
    bakery_monitor_heartbeat_interval_seconds: int = 30
    bakery_collection_poll_interval_seconds: int = 10
    bakery_request_timeout_seconds: int = 15
    bakery_max_retries: int = 2
    bakery_poll_interval_seconds: float = 2.0
    bakery_poll_timeout_seconds: int = 60
    bakery_active_provider: str = ""
    catch_all_recipe_name: str = "fallback-recipe"
    bakery_rackspace_confirmed_solved_status: str = "confirmed solved"

    # ==========================================================================
    # Alert Suppression Settings
    # ==========================================================================
    suppressions_enabled: bool = True
    suppression_lifecycle_enabled: bool = True
    suppression_lifecycle_interval_seconds: int = 30
    suppression_lifecycle_batch_limit: int = 25


settings = Settings()


@lru_cache
def get_settings() -> Settings:
    return Settings()
