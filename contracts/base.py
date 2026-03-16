"""Base Pydantic models for shared contracts."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict


class ContractModel(BaseModel):
    """Strict base model for externally visible contracts."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class ORMContractModel(ContractModel):
    """Strict contract model that can be hydrated from ORM objects."""

    model_config = ConfigDict(extra="forbid", from_attributes=True, str_strip_whitespace=True)
