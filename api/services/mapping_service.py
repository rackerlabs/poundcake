"""Database-backed mapping service for alert-to-action mappings.

This service replaces the file-based YAML mapping approach with database storage
for easier management and UI integration.
"""

import fnmatch
import logging
import re
from datetime import datetime
from typing import Any

import yaml
from sqlalchemy.orm import Session

from api.models.models import Alert, Mapping

logger = logging.getLogger(__name__)


class MappingService:
    """Service for managing alert-to-action mappings in the database."""

    @staticmethod
    def list_mappings(db: Session, enabled_only: bool = False) -> dict[str, Any]:
        """List all mappings.

        Args:
            db: Database session
            enabled_only: If True, only return enabled mappings

        Returns:
            Dictionary of mappings keyed by alert_name
        """
        query = db.query(Mapping)
        if enabled_only:
            query = query.filter(Mapping.enabled)

        mappings = query.order_by(Mapping.alert_name).all()

        return {
            mapping.alert_name: {
                "id": mapping.id,
                "handler": mapping.handler,
                "config": mapping.config,
                "description": mapping.description,
                "enabled": mapping.enabled,
                "created_at": mapping.created_at.isoformat() if mapping.created_at else None,
                "updated_at": mapping.updated_at.isoformat() if mapping.updated_at else None,
            }
            for mapping in mappings
        }

    @staticmethod
    def get_mapping(db: Session, alert_name: str) -> dict[str, Any] | None:
        """Get a specific mapping by alert name.

        Args:
            db: Database session
            alert_name: The alert name to look up

        Returns:
            Mapping configuration or None if not found
        """
        mapping = db.query(Mapping).filter(Mapping.alert_name == alert_name).first()
        if not mapping:
            return None

        return {
            "id": mapping.id,
            "alert_name": mapping.alert_name,
            "handler": mapping.handler,
            "config": mapping.config,
            "description": mapping.description,
            "enabled": mapping.enabled,
            "created_at": mapping.created_at.isoformat() if mapping.created_at else None,
            "updated_at": mapping.updated_at.isoformat() if mapping.updated_at else None,
        }

    @staticmethod
    def create_mapping(
        db: Session,
        alert_name: str,
        config: dict[str, Any],
        handler: str = "yaml_config",
        description: str | None = None,
        created_by: str | None = None,
    ) -> dict[str, Any]:
        """Create a new mapping.

        Args:
            db: Database session
            alert_name: The alert name pattern
            config: The mapping configuration (actions, conditions, etc.)
            handler: The handler type (default: yaml_config)
            description: Optional description
            created_by: Username who created the mapping

        Returns:
            Created mapping data

        Raises:
            ValueError: If mapping already exists
        """
        existing = db.query(Mapping).filter(Mapping.alert_name == alert_name).first()
        if existing:
            raise ValueError(f"Mapping for '{alert_name}' already exists")

        mapping = Mapping(
            alert_name=alert_name,
            handler=handler,
            config=config,
            description=description,
            enabled=True,
            created_by=created_by,
            updated_by=created_by,
        )
        db.add(mapping)
        db.commit()
        db.refresh(mapping)

        logger.info("Created mapping for alert: %s", alert_name)

        return {
            "id": mapping.id,
            "alert_name": mapping.alert_name,
            "handler": mapping.handler,
            "config": mapping.config,
            "description": mapping.description,
            "enabled": mapping.enabled,
        }

    @staticmethod
    def update_mapping(
        db: Session,
        alert_name: str,
        config: dict[str, Any] | None = None,
        handler: str | None = None,
        description: str | None = None,
        enabled: bool | None = None,
        updated_by: str | None = None,
    ) -> dict[str, Any]:
        """Update an existing mapping.

        Args:
            db: Database session
            alert_name: The alert name to update
            config: New configuration (if provided)
            handler: New handler type (if provided)
            description: New description (if provided)
            enabled: New enabled status (if provided)
            updated_by: Username who updated the mapping

        Returns:
            Updated mapping data

        Raises:
            ValueError: If mapping not found
        """
        mapping = db.query(Mapping).filter(Mapping.alert_name == alert_name).first()
        if not mapping:
            raise ValueError(f"Mapping for '{alert_name}' not found")

        if config is not None:
            mapping.config = config
        if handler is not None:
            mapping.handler = handler
        if description is not None:
            mapping.description = description
        if enabled is not None:
            mapping.enabled = enabled
        if updated_by is not None:
            mapping.updated_by = updated_by

        mapping.updated_at = datetime.utcnow()
        db.commit()
        db.refresh(mapping)

        logger.info("Updated mapping for alert: %s", alert_name)

        return {
            "id": mapping.id,
            "alert_name": mapping.alert_name,
            "handler": mapping.handler,
            "config": mapping.config,
            "description": mapping.description,
            "enabled": mapping.enabled,
        }

    @staticmethod
    def delete_mapping(db: Session, alert_name: str) -> bool:
        """Delete a mapping.

        Args:
            db: Database session
            alert_name: The alert name to delete

        Returns:
            True if deleted, False if not found
        """
        mapping = db.query(Mapping).filter(Mapping.alert_name == alert_name).first()
        if not mapping:
            return False

        db.delete(mapping)
        db.commit()

        logger.info("Deleted mapping for alert: %s", alert_name)
        return True

    @staticmethod
    def export_mappings(db: Session) -> str:
        """Export all mappings as YAML.

        Args:
            db: Database session

        Returns:
            YAML string of all mappings
        """
        mappings = db.query(Mapping).order_by(Mapping.alert_name).all()

        export_data = {
            "alerts": {
                mapping.alert_name: {
                    "handler": mapping.handler,
                    **(mapping.config or {}),
                }
                for mapping in mappings
            }
        }

        return yaml.dump(export_data, default_flow_style=False, sort_keys=False)

    @staticmethod
    def import_mappings(
        db: Session,
        yaml_content: str,
        overwrite: bool = False,
        imported_by: str | None = None,
    ) -> dict[str, Any]:
        """Import mappings from YAML content.

        Args:
            db: Database session
            yaml_content: YAML string to import
            overwrite: If True, overwrite existing mappings
            imported_by: Username who imported the mappings

        Returns:
            Import statistics
        """
        data = yaml.safe_load(yaml_content)
        if not data or "alerts" not in data:
            raise ValueError("Invalid YAML format: expected 'alerts' key")

        alerts = data["alerts"]
        imported = 0
        skipped = 0
        updated = 0
        errors = []

        for alert_name, config in alerts.items():
            try:
                existing = db.query(Mapping).filter(Mapping.alert_name == alert_name).first()

                # Extract handler from config
                handler = config.pop("handler", "yaml_config")

                if existing:
                    if overwrite:
                        existing.handler = handler
                        existing.config = config
                        existing.updated_by = imported_by
                        existing.updated_at = datetime.utcnow()
                        updated += 1
                    else:
                        skipped += 1
                else:
                    mapping = Mapping(
                        alert_name=alert_name,
                        handler=handler,
                        config=config,
                        enabled=True,
                        created_by=imported_by,
                        updated_by=imported_by,
                    )
                    db.add(mapping)
                    imported += 1

            except Exception as e:
                errors.append({"alert_name": alert_name, "error": str(e)})

        db.commit()

        logger.info(
            "Imported mappings: %d imported, %d updated, %d skipped, %d errors",
            imported,
            updated,
            skipped,
            len(errors),
        )

        return {
            "imported": imported,
            "updated": updated,
            "skipped": skipped,
            "errors": errors,
        }

    @staticmethod
    def get_mapping_for_alert(db: Session, alert: Alert) -> dict[str, Any] | None:
        """Find the matching mapping for an alert.

        This method tries to find a mapping by:
        1. Exact match on alert_name
        2. Wildcard/pattern match on alert_name

        Args:
            db: Database session
            alert: The alert to find a mapping for

        Returns:
            Matching mapping configuration or None
        """
        alert_name = alert.alert_name

        # Try exact match first
        mapping = (
            db.query(Mapping).filter(Mapping.alert_name == alert_name, Mapping.enabled).first()
        )

        if mapping:
            return {
                "alert_name": mapping.alert_name,
                "handler": mapping.handler,
                "config": mapping.config,
            }

        # Try pattern matching
        all_mappings = db.query(Mapping).filter(Mapping.enabled).all()
        for mapping in all_mappings:
            pattern = mapping.alert_name
            # Support glob-style wildcards
            if "*" in pattern or "?" in pattern:
                if fnmatch.fnmatch(alert_name, pattern):
                    return {
                        "alert_name": mapping.alert_name,
                        "handler": mapping.handler,
                        "config": mapping.config,
                    }
            # Support regex patterns (enclosed in /)
            elif pattern.startswith("/") and pattern.endswith("/"):
                regex = pattern[1:-1]
                if re.match(regex, alert_name):
                    return {
                        "alert_name": mapping.alert_name,
                        "handler": mapping.handler,
                        "config": mapping.config,
                    }

        return None

    @staticmethod
    def toggle_mapping(db: Session, alert_name: str, enabled: bool) -> dict[str, Any]:
        """Toggle the enabled status of a mapping.

        Args:
            db: Database session
            alert_name: The alert name
            enabled: New enabled status

        Returns:
            Updated mapping data

        Raises:
            ValueError: If mapping not found
        """
        mapping = db.query(Mapping).filter(Mapping.alert_name == alert_name).first()
        if not mapping:
            raise ValueError(f"Mapping for '{alert_name}' not found")

        mapping.enabled = enabled
        mapping.updated_at = datetime.utcnow()
        db.commit()

        logger.info("Toggled mapping for alert %s: enabled=%s", alert_name, enabled)

        return {
            "alert_name": mapping.alert_name,
            "enabled": mapping.enabled,
        }
