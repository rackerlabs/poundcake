"""Shared status vocabularies for dishes, orders, and StackStorm."""

ST2_TERMINAL_STATUSES = {"succeeded", "failed", "canceled", "timeout", "abandoned"}
ST2_FAILURE_STATUSES = {"failed", "canceled", "timeout", "abandoned"}

DISH_TERMINAL_PROCESSING_STATUSES = {"complete", "failed", "abandoned", "timeout", "canceled"}

ORDER_TERMINAL_PROCESSING_STATUSES = {"complete", "failed", "canceled"}
