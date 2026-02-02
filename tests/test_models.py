#  ___                        _  ____      _
# |  _ \ ___  _   _ _ __   __| |/ ___|__ _| | _____
# | |_) / _ \| | | | '_ \ / _` | |   / _` | |/ / _ \
# |  __/ (_) | |_| | | | | (_| | |__| (_| |   <  __/
# |_|   \___/ \__,_|_| |_|\__,_|\____\__,_|_|\_\___|
#               Test database models
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
        starts_at="2026-01-01T00:00:00Z", # Required by model
        counter=1,
        processing_status="new",
    )
    assert alert.alert_name == "TestAlert"
    assert alert.counter == 1

def test_recipe_model_creation():
    """Test Recipe model can be instantiated with new hierarchy."""
    recipe = Recipe(
        name="TestRecipe", 
        description="Testing Recipe Model",
        enabled=True
    )
    assert recipe.name == "TestRecipe"

def test_oven_model_creation():
    """Test Oven model aligns with execution fields."""
    oven = Oven(
        req_id="test-req-123", 
        recipe_id=1, 
        ingredient_id=1,
        task_order=1,
        processing_status="new"
    )
    assert oven.req_id == "test-req-123"
    assert oven.processing_status == "new"
