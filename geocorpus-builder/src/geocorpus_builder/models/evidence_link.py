"""EvidenceLink model -- data evidence backing corpus unit claims."""

from typing import Optional, Union

from pydantic import BaseModel, Field, field_validator


class EvidenceLink(BaseModel):
    """A single evidence record linking a corpus unit to source data."""

    evidence_id: str = Field(description="Unique evidence ID")
    corpus_id: Optional[str] = Field(default=None, description="Linked corpus unit ID")
    evidence_type: str = Field(description="Type of evidence (statistic, raster, vector, etc.)")
    source_table: str = Field(description="Table or file where evidence comes from")
    source_id: str = Field(description="Object ID or row ID in source table")
    variable: str = Field(description="Variable name")
    statistic: str = Field(description="Statistic type (mean, median, trend, etc.)")
    value: Optional[Union[str, float, None]] = Field(default=None, description="Numeric or textual evidence value")
    unit: Optional[str] = Field(default=None, description="Unit of measurement")
    time_range: Optional[str] = Field(default=None, description="Time range")
    spatial_scale: Optional[str] = Field(default=None, description="Spatial scale")
    notes: Optional[str] = Field(default=None, description="Additional notes")

    @field_validator("evidence_id")
    @classmethod
    def evidence_id_not_empty(cls, v: str) -> str:
        if not v or not v.strip():
            raise ValueError("evidence_id must not be empty")
        return v.strip()

    @field_validator("source_table")
    @classmethod
    def source_table_not_empty(cls, v: str) -> str:
        if not v or not v.strip():
            raise ValueError("source_table must not be empty")
        return v.strip()

    @field_validator("source_id")
    @classmethod
    def source_id_not_empty(cls, v: str) -> str:
        if not v or not v.strip():
            raise ValueError("source_id must not be empty")
        return v.strip()
