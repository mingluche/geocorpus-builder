"""GeoConcept model -- geographical concept dictionary entry."""

from typing import Optional

from pydantic import BaseModel, Field


class GeoConcept(BaseModel):
    """A geographical concept definition."""

    concept_id: str = Field(description="Unique concept ID")
    zh: str = Field(description="Chinese term")
    en: str = Field(description="English term")
    definition: str = Field(description="Short definition")
    domain: str = Field(description="Scientific domain")
    data_type: str = Field(description="GeoObject / GeoField / GeoRegion / GeoEvent / GeoRelation / indicator")
    typical_unit: Optional[str] = Field(default=None, description="Typical unit")
    related_variables: list[str] = Field(default_factory=list, description="Related variable IDs")
