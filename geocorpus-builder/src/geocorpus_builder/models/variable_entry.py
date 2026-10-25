"""VariableEntry model -- variable dictionary entry."""

from typing import Optional

from pydantic import BaseModel, Field


class VariableEntry(BaseModel):
    """A variable definition in the variable dictionary."""

    variable_id: str = Field(description="Unique variable ID")
    zh: str = Field(description="Chinese name")
    en: str = Field(description="English name")
    domain: str = Field(description="Scientific domain")
    description: str = Field(description="Definition and meaning")
    unit: Optional[str] = Field(default=None, description="Unit of measurement")
    spatial_support: str = Field(description="Spatial support (grid, object, region, point, event)")
    temporal_support: str = Field(description="Temporal support (static, yearly, monthly, daily, event, period)")
    aggregation_rule: str = Field(description="Aggregation rule (mean, sum, area_weighted_mean, etc.)")
