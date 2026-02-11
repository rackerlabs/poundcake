#!/usr/bin/env python3
"""Base mixer interface for ticketing systems."""

from abc import ABC, abstractmethod
from typing import Dict, Any


class BaseMixer(ABC):
    """
    Abstract base class for ticketing system mixers.

    All mixers must implement the process_request method.
    """

    def __init__(self) -> None:
        """Initialize mixer."""
        pass

    @abstractmethod
    async def process_request(self, action: str, data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Process a ticket request.

        Args:
            action: Action to perform (create, update, close, comment, search)
            data: Request data specific to the action

        Returns:
            Dictionary with:
                - success: bool indicating if request succeeded
                - ticket_id: str ticket identifier (if applicable)
                - data: Any additional response data
                - error: str error message (if failed)

            For search actions, returns:
                - success: bool
                - data: dict with "results" (list), "count" (int), "total" (int)

        Example (single ticket):
            {
                "success": True,
                "ticket_id": "INC0012345",
                "data": {"url": "https://..."},
            }

        Example (search):
            {
                "success": True,
                "data": {
                    "results": [...],
                    "count": 10,
                    "total": 42,
                },
            }
        """
        pass

    @abstractmethod
    async def validate_credentials(self) -> bool:
        """
        Validate mixer credentials.

        Returns:
            True if credentials are valid, False otherwise
        """
        pass
