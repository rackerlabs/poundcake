# ╔════════════════════════════════════════════════════════════════╗
#  ____                        _  ____      _         
# |  _ \ ___  _   _ _ __   __| |/ ___|__ _| | _____ 
# | |_) / _ \| | | | '_ \ / _` | |   / _` | |/ / _ \
# |  __/ (_) | |_| | | | | (_| | |__| (_| |   <  __/
# |_|   \___/ \__,_|_| |_|\__,_|\____\__,_|_|\_\___|
# ╚════════════════════════════════════════════════════════════════╝
#
"""Test database models."""

from api.models.models import Alert, Recipe, Oven


def test_alert_model_creation():
    """Test Alert model can be instantiated."""
    alert = Alert(
        req_id="test-req-123",
        fingerprint="test-fp-456",
        alert_status="firing",
        alert_name="TestAlert",
        group_name="TestGroup",
        severity="critical",
        labels={"test": "label"},
        counter=1,
        processing_status="new"
    )
    assert alert.alert_name == "TestAlert"
    assert alert.counter == 1


def test_recipe_model_creation():
    """Test Recipe model can be instantiated."""
    recipe = Recipe(
        name="TestRecipe",
        st2_workflow_ref="test.workflow",
        task_list="task1,task2,task3"
    )
    assert recipe.name == "TestRecipe"
    assert recipe.st2_workflow_ref == "test.workflow"


def test_oven_model_creation():
    """Test Oven model can be instantiated."""
    oven = Oven(
        req_id="test-req-123",
        recipe_id=1,
        action_id="test-action-id",
        status="pending"
    )
    assert oven.req_id == "test-req-123"
    assert oven.status == "pending"
