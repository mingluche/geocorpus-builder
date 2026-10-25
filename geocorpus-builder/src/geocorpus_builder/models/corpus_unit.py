"""CorpusUnit model -- the central data type for geocorpus."""

import re
from typing import Optional

from pydantic import BaseModel, Field, field_validator

from .enums import TextType, Domain, GeoObjectType, SpatialScale, ClaimType, Confidence


class CorpusUnit(BaseModel):
    """A single corpus unit: text linked to geo object, variable, time, space, and evidence."""

    corpus_id: str = Field(description="Unique ID of corpus unit, must start with GC_")
    text: str = Field(description="Natural-language statement")
    text_type: str = Field(default="definition", description="Type of text")
    domain: str = Field(default="cryosphere", description="Scientific domain")
    subdomain: Optional[str] = Field(default=None, description="Subdomain")
    geo_object_type: Optional[str] = Field(default=None, description="Type of geographical object")
    geo_object_id: str = Field(description="Specific object ID (e.g. glacier_id, grid_id)")
    spatial_scale: Optional[str] = Field(default=None, description="Spatial scale")
    time_range: str = Field(default="not_applicable", description="Time range, e.g. 2017-2024")
    variable: str = Field(description="Main variable discussed")
    claim_type: Optional[str] = Field(default=None, description="Type of claim made")
    evidence_ids: list[str] = Field(default_factory=list, description="Linked evidence IDs")
    confidence: Optional[str] = Field(default=None, description="Confidence level")
    source: Optional[str] = Field(default=None, description="Source of the record")

    @field_validator("corpus_id")
    @classmethod
    def corpus_id_pattern(cls, v: str) -> str:
        if not re.match(r"^GC_", v):
            raise ValueError(f"corpus_id must start with 'GC_', got '{v}'")
        return v

    @field_validator("text")
    @classmethod
    def text_not_empty(cls, v: str) -> str:
        if not v or not v.strip():
            raise ValueError("text must not be empty")
        return v.strip()

    @field_validator("geo_object_id")
    @classmethod
    def geo_object_id_not_empty(cls, v: str) -> str:
        if not v or not v.strip():
            raise ValueError("geo_object_id must not be empty")
        return v.strip()

    @field_validator("variable")
    @classmethod
    def variable_not_empty(cls, v: str) -> str:
        if not v or not v.strip():
            raise ValueError("variable must not be empty")
        return v.strip()
