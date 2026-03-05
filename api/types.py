#  ___                        _  ____      _
# |  _ \ ___  _   _ _ __   __| |/ ___|__ _| | _____
# | |_) / _ \| | | | '_ \ / _` | |   / _` | |/ / _ \
# |  __/ (_) | |_| | | | | (_| | |__| (_| |   <  __/
# |_|   \___/ \__,_|_| |_|\__,_|\____\__,_|_|\_\___|
#
"""
Strict type definitions using Literal types for better type safety.

This module defines all valid status values and other constrained types
using Python's Literal type for compile-time type checking and better
IDE support.
"""

from typing import Literal

# =============================================================================
# Processing Status Types
# =============================================================================

# Dish processing statuses
DishProcessingStatus = Literal[
    "new",
    "processing",
    "finalizing",
    "complete",
    "failed",
    "abandoned",
    "timeout",
    "canceled",
]

# Order processing statuses (subset of dish statuses)
OrderProcessingStatus = Literal[
    "new",
    "processing",
    "resolving",
    "complete",
    "failed",
    "canceled",
]

# Terminal statuses for dishes
DishTerminalStatus = Literal[
    "complete",
    "failed",
    "abandoned",
    "timeout",
    "canceled",
]

# Terminal statuses for orders
OrderTerminalStatus = Literal[
    "complete",
    "failed",
    "canceled",
]

# =============================================================================
# Alert Status Types
# =============================================================================

AlertStatus = Literal[
    "firing",
    "resolved",
]

# =============================================================================
# StackStorm Execution Status Types
# =============================================================================

ST2ExecutionStatus = Literal[
    "requested",
    "scheduled",
    "running",
    "succeeded",
    "failed",
    "canceled",
    "canceling",
    "paused",
    "pausing",
    "resuming",
    "pending",
    "timeout",
    "abandoned",
]

ST2TerminalStatus = Literal[
    "succeeded",
    "failed",
    "canceled",
    "timeout",
    "abandoned",
]

ST2FailureStatus = Literal[
    "failed",
    "canceled",
    "timeout",
    "abandoned",
]

# =============================================================================
# Recipe Ingredient Types
# =============================================================================

OnSuccessAction = Literal[
    "continue",
    "stop",
]

OnFailureAction = Literal[
    "continue",
    "stop",
    "retry",
]

RunPhase = Literal[
    "firing",
    "resolving",
    "both",
]

DishRunPhase = Literal[
    "firing",
    "resolving",
]

ExecutionPurpose = Literal[
    "remediation",
    "comms",
    "utility",
]

# Backward-compatible alias.
IngredientKind = ExecutionPurpose

# =============================================================================
# Sort Order Types
# =============================================================================

SortOrder = Literal[
    "asc",
    "desc",
]

# =============================================================================
# Log Format Types
# =============================================================================

LogFormat = Literal[
    "json",
    "console",
]

# =============================================================================
# Suppression Types
# =============================================================================

SuppressionScope = Literal[
    "all",
    "matchers",
]

SuppressionStatus = Literal[
    "scheduled",
    "active",
    "expired",
    "canceled",
]

SuppressionMatcherOperator = Literal[
    "eq",
    "neq",
    "regex",
    "nregex",
    "exists",
    "not_exists",
]

# =============================================================================
# Unified Execution Types
# =============================================================================

CanonicalExecutionStatus = Literal[
    "queued",
    "running",
    "succeeded",
    "failed",
    "canceled",
]
