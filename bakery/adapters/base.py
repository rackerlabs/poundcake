#!/usr/bin/env python3
"""Base adapter interface for ticketing systems."""

from abc import ABC, abstractmethod
from typing import Dict, Any


class BaseAdapter(ABC):
    """
    Abstract base class for ticketing system adapters.

    All adapters must implement the process_request method.
    """

    def __init__(self) -> None:
        """Initialize adapter."""
        pass

    @abstractmethod
    async def process_request(
        self, action: str, data: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        Process a ticket request.

        Args:
            action: Action to perform (create, update, close, comment, etc)
            data: Request data specific to the action

        Returns:
            Dictionary with:
                - success: bool indicating if request succeeded
                - ticket_id: str ticket identifier (if applicable)
                - data: Any additional response data
                - error: str error message (if failed)

        Example:
            {
                "success": True,
                "ticket_id": "INC0012345",
                "data": {"url": "https://..."},
            }
        """
        pass

    @abstractmethod
    async def validate_credentials(self) -> bool:
        """
        Validate adapter credentials.

        Returns:
            True if credentials are valid, False otherwise
        """
        pass
