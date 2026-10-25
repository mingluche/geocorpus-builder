"""Relation model -- spatial/tabular relation definition."""

from pydantic import BaseModel, Field


class RelationDefinition(BaseModel):
    """A relation type definition (e.g. object-grid overlap, neighbor-distance)."""

    relation_id: str = Field(description="Unique relation ID")
    zh: str = Field(description="Chinese name")
    en: str = Field(description="English name")
    description: str = Field(description="Description of the relation")
    required_fields: list[str] = Field(description="Required fields for this relation")
    typical_use: str = Field(description="Typical use case")
