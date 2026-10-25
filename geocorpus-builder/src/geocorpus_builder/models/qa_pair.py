"""QAPair model -- question-answer pairs for guiding agent responses."""

from typing import Optional

from pydantic import BaseModel, Field, field_validator


class QAPair(BaseModel):
    """A question-answer pair for guiding the GeoCorpus agent."""

    qa_id: str = Field(description="Unique QA ID")
    question: str = Field(description="Question text")
    answer: str = Field(description="Grounded answer")
    domain: str = Field(description="Domain classification")
    required_tables: list[str] = Field(default_factory=list, description="Tables required to answer")
    evidence_ids: list[str] = Field(default_factory=list, description="Evidence IDs used in answer")
    answer_rule: Optional[str] = Field(default=None, description="How the answer should be generated")

    @field_validator("qa_id")
    @classmethod
    def qa_id_not_empty(cls, v: str) -> str:
        if not v or not v.strip():
            raise ValueError("qa_id must not be empty")
        return v.strip()
