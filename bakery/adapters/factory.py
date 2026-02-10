#!/usr/bin/env python3
"""Factory for creating adapter instances."""

from typing import Dict, Type
from bakery.adapters.base import BaseAdapter
from bakery.adapters.servicenow import ServiceNowAdapter
from bakery.adapters.jira import JiraAdapter
from bakery.adapters.github import GitHubAdapter
from bakery.adapters.pagerduty import PagerDutyAdapter
from bakery.adapters.rackspace_core import RackspaceCoreAdapter


# Registry of available adapters
ADAPTER_REGISTRY: Dict[str, Type[BaseAdapter]] = {
    "servicenow": ServiceNowAdapter,
    "jira": JiraAdapter,
    "github": GitHubAdapter,
    "pagerduty": PagerDutyAdapter,
    "rackspace_core": RackspaceCoreAdapter,
}


def get_adapter(adapter_type: str) -> BaseAdapter:
    """
    Get adapter instance by type.

    Args:
        adapter_type: Type of adapter (servicenow, jira, github, etc)

    Returns:
        Adapter instance

    Raises:
        ValueError: If adapter_type is not registered
    """
    adapter_class = ADAPTER_REGISTRY.get(adapter_type)
    if not adapter_class:
        raise ValueError(
            f"Unknown adapter type: {adapter_type}. "
            f"Available: {', '.join(ADAPTER_REGISTRY.keys())}"
        )

    return adapter_class()


def list_adapters() -> list[str]:
    """
    Get list of available adapter types.

    Returns:
        List of adapter type names
    """
    return list(ADAPTER_REGISTRY.keys())
