#  ___                        _  ____      _
# |  _ \ ___  _   _ _ __   __| |/ ___|__ _| | _____
# | |_) / _ \| | | | '_ \ / _` | |   / _` | |/ / _ \
# |  __/ (_) | |_| | | | | (_| | |__| (_| |   <  __/
# |_|   \___/ \__,_|_| |_|\__,_|\____\__,_|_|\_\___|
#
"""API routes and endpoints for PoundCake."""

# Keep package imports minimal to avoid circular import issues.
from . import (
    health,
    auth,
    cook,
    prometheus,
    recipes,
    dishes,
    orders,
    ingredients,
    webhook,
    settings,
)

__all__ = [
    "health",
    "auth",
    "cook",
    "prometheus",
    "recipes",
    "dishes",
    "orders",
    "ingredients",
    "webhook",
    "settings",
]
