"""Unit tests for shared order transition helpers."""

from api.core.statuses import (
    can_transition_to_resolving,
    is_order_terminal,
    should_keep_active,
)


def test_is_order_terminal():
    assert is_order_terminal("complete") is True
    assert is_order_terminal("failed") is True
    assert is_order_terminal("canceled") is True
    assert is_order_terminal("processing") is False


def test_can_transition_to_resolving_from_dish_terminal():
    assert can_transition_to_resolving("processing", "dish_terminal") is True
    assert can_transition_to_resolving("new", "dish_terminal") is False
    assert can_transition_to_resolving("resolving", "dish_terminal") is False
    assert can_transition_to_resolving("failed", "dish_terminal") is False


def test_can_transition_to_resolving_from_alert_resolved():
    assert can_transition_to_resolving("new", "alert_resolved") is True
    assert can_transition_to_resolving("processing", "alert_resolved") is True
    assert can_transition_to_resolving("resolving", "alert_resolved") is True
    assert can_transition_to_resolving("complete", "alert_resolved") is False


def test_should_keep_active():
    assert should_keep_active("new") is True
    assert should_keep_active("processing") is True
    assert should_keep_active("resolving") is True
    assert should_keep_active("complete") is False
    assert should_keep_active("failed") is False


def test_lifecycle_sequence_late_resolved_does_not_reopen_complete():
    # firing webhook -> prep-chef cook
    status = "new"
    status = "processing"

    # timer sees dish terminal
    assert can_transition_to_resolving(status, "dish_terminal") is True
    status = "resolving"

    # resolve endpoint finalizes order
    status = "complete"
    assert is_order_terminal(status) is True
    assert should_keep_active(status) is False

    # late duplicate resolved webhook should not reopen
    assert can_transition_to_resolving(status, "alert_resolved") is False
