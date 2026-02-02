#  ___                        _  ____      _
# |  _ \ ___  _   _ _ __   __| |/ ___|__ _| | _____
# | |_) / _ \| | | | '_ \ / _` | |   / _` | |/ / _ \
# |  __/ (_) | |_| | | | | (_| | |__| (_| |   <  __/
# |_|   \___/ \__,_|_| |_|\__,_|\____\__,_|_|\_\___|
#
"""Pydantic schemas for PoundCake API."""

from pydantic import BaseModel, ConfigDict
from typing import List, Optional, Dict, Any
from datetime import datetime

# --- Health & Stats ---
class HealthResponse(BaseModel):
    status: str
    version: str
    database: str
    stackstorm: str
    timestamp: datetime

class StatsResponse(BaseModel):
    total_alerts: int
    total_recipes: int
    total_executions: int
    alerts_by_processing_status: Dict[str, int]
    alerts_by_alert_status: Dict[str, int]
    executions_by_status: Dict[str, int]
    recent_alerts: int

# --- Ingredients (ST2 Action Mapping) ---
class IngredientBase(BaseModel):
    name: str
    st2_action: str
    description: Optional[str] = None

class IngredientResponse(IngredientBase):
    id: int
    model_config = ConfigDict(from_attributes=True)

# --- Recipes (Alert to Ingredient Mapping) ---
class RecipeBase(BaseModel):
    alert_name: str
    ingredient_id: int
    is_active: bool = True

class RecipeResponse(RecipeBase):
    id: int
    ingredient: IngredientResponse
    model_config = ConfigDict(from_attributes=True)

# --- Oven (Execution Tracking) ---
class OvenBase(BaseModel):
    req_id: str
    processing_status: str = "new"

class OvenResponse(OvenBase):
    id: int
    recipe_id: int
    # These fields are populated as the worker proxies through the API
    action_id: Optional[str] = None  # ST2 Execution ID
    st2_status: Optional[str] = None
    created_at: datetime
    
    # We include the st2_action directly here so the worker 
    # doesn't have to do complex joins
    st2_action: Optional[str] = None 
    
    model_config = ConfigDict(from_attributes=True)

# --- Alerts ---
class AlertBase(BaseModel):
    alert_name: str
    alert_status: str  # firing or resolved
    labels: Dict[str, Any]
    annotations: Dict[str, Any]
    req_id: str

class AlertResponse(AlertBase):
    id: int
    processing_status: str
    created_at: datetime
    model_config = ConfigDict(from_attributes=True)
