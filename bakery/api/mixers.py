#!/usr/bin/env python3
"""Mixer management endpoints for Bakery."""

from typing import Any, List
from fastapi import APIRouter, HTTPException

from bakery.mixer.factory import get_mixer, list_mixers
from bakery.schemas import MixerListResponse, MixerInfo, MixerValidateResponse

router = APIRouter()

MIXER_ACTIONS = {
    "servicenow": ["create", "update", "close", "comment", "search"],
    "jira": ["create", "update", "close", "comment", "search"],
    "github": ["create", "update", "close", "comment", "search"],
    "pagerduty": ["create", "update", "close", "comment", "search"],
    "rackspace_core": ["create", "update", "close", "comment", "search"],
    "teams": ["create", "update", "close", "comment"],
    "discord": ["create", "update", "close", "comment"],
}


@router.get(
    "/mixers",
    response_model=MixerListResponse,
    summary="List available mixers",
    description=(
        "Returns all registered mixer types and their current configuration "
        "status. Use this to discover which ticketing or messaging systems Bakery can "
        "communicate with."
    ),
)
async def get_available_mixers() -> MixerListResponse:
    """
    List all available mixer types.

    Returns information about each registered mixer including
    whether credentials are configured.
    """
    mixers: List[MixerInfo] = []

    for mixer_type in list_mixers():
        try:
            mixer = get_mixer(mixer_type)
            # Check if basic credentials are set (without making API calls)
            has_credentials = _check_credentials_configured(mixer_type, mixer)
            mixers.append(
                MixerInfo(
                    mixer_type=mixer_type,
                    actions=MIXER_ACTIONS.get(mixer_type, ["create", "update", "close"]),
                    configured=has_credentials,
                )
            )
        except Exception:
            mixers.append(
                MixerInfo(
                    mixer_type=mixer_type,
                    actions=MIXER_ACTIONS.get(mixer_type, ["create", "update", "close"]),
                    configured=False,
                )
            )

    return MixerListResponse(mixers=mixers, count=len(mixers))


@router.post(
    "/mixers/{mixer_type}/validate",
    response_model=MixerValidateResponse,
    summary="Validate mixer credentials",
    description=(
        "Tests connectivity and authentication with the specified communication "
        "system. Makes a live API call to verify the configured credentials "
        "are valid."
    ),
)
async def validate_mixer_credentials(mixer_type: str) -> MixerValidateResponse:
    """
    Validate credentials for a specific mixer.

    Makes a live API call to the ticketing system to verify
    that the configured credentials are working.

    Args:
        mixer_type: Mixer type to validate (e.g. servicenow, jira)

    Raises:
        HTTPException: If mixer type is invalid
    """
    available = list_mixers()
    if mixer_type not in available:
        raise HTTPException(
            status_code=404,
            detail=f"Unknown mixer_type: {mixer_type}. Available: {', '.join(available)}",
        )

    try:
        mixer = get_mixer(mixer_type)
        valid = await mixer.validate_credentials()
        return MixerValidateResponse(
            mixer_type=mixer_type,
            valid=valid,
            message="Credentials are valid" if valid else "Credential validation failed",
        )
    except Exception as e:
        return MixerValidateResponse(
            mixer_type=mixer_type,
            valid=False,
            message=f"Validation error: {str(e)}",
        )


def _check_credentials_configured(mixer_type: str, mixer: Any) -> bool:
    """
    Check whether a mixer has its credentials configured (non-empty).

    This does NOT make API calls -- it only checks that the required
    environment variables are set.
    """
    if mixer_type == "servicenow":
        return bool(
            getattr(mixer, "base_url", None)
            and getattr(mixer, "username", None)
            and getattr(mixer, "password", None)
        )
    elif mixer_type == "jira":
        return bool(
            getattr(mixer, "base_url", None)
            and getattr(mixer, "username", None)
            and getattr(mixer, "api_token", None)
        )
    elif mixer_type == "github":
        return bool(getattr(mixer, "token", None))
    elif mixer_type == "pagerduty":
        return bool(getattr(mixer, "api_key", None))
    elif mixer_type in {"teams", "discord"}:
        return bool(getattr(mixer, "webhook_url", None))
    elif mixer_type == "rackspace_core":
        return bool(
            getattr(mixer, "base_url", None)
            and getattr(mixer, "username", None)
            and getattr(mixer, "password", None)
        )
    return False
