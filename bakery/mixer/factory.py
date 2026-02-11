#!/usr/bin/env python3
"""Factory for creating mixer instances."""

from typing import Dict, Type
from bakery.mixer.base import BaseMixer
from bakery.mixer.servicenow import ServiceNowMixer
from bakery.mixer.jira import JiraMixer
from bakery.mixer.github import GitHubMixer
from bakery.mixer.pagerduty import PagerDutyMixer
from bakery.mixer.rackspace_core import RackspaceCoreMixer

# Registry of available mixers
MIXER_REGISTRY: Dict[str, Type[BaseMixer]] = {
    "servicenow": ServiceNowMixer,
    "jira": JiraMixer,
    "github": GitHubMixer,
    "pagerduty": PagerDutyMixer,
    "rackspace_core": RackspaceCoreMixer,
}


def get_mixer(mixer_type: str) -> BaseMixer:
    """
    Get mixer instance by type.

    Args:
        mixer_type: Type of mixer (servicenow, jira, github, etc)

    Returns:
        Mixer instance

    Raises:
        ValueError: If mixer_type is not registered
    """
    mixer_class = MIXER_REGISTRY.get(mixer_type)
    if not mixer_class:
        raise ValueError(
            f"Unknown mixer type: {mixer_type}. " f"Available: {', '.join(MIXER_REGISTRY.keys())}"
        )

    return mixer_class()


def list_mixers() -> list[str]:
    """
    Get list of available mixer types.

    Returns:
        List of mixer type names
    """
    return list(MIXER_REGISTRY.keys())
