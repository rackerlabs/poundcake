#  ___                        _  ____      _
# |  _ \ ___  _   _ _ __   __| |/ ___|__ _| | _____
# | |_) / _ \| | | | '_ \ / _` | |   / _` | |/ / _ \
# |  __/ (_) | |_| | | | | (_| | |__| (_| |   <  __/
# |_|   \___/ \__,_|_| |_|\__,_|\____\__,_|_|\_\___|
#
"""Shared status vocabularies for dishes, orders, and StackStorm."""

ST2_TERMINAL_STATUSES = {"succeeded", "failed", "canceled", "timeout", "abandoned"}
ST2_FAILURE_STATUSES = {"failed", "canceled", "timeout", "abandoned"}

DISH_TERMINAL_PROCESSING_STATUSES = {"complete", "failed", "abandoned", "timeout", "canceled"}

ORDER_TERMINAL_PROCESSING_STATUSES = {"complete", "failed", "canceled"}
