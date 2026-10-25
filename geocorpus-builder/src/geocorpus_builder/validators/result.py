"""Validation data types shared across validators."""

from dataclasses import dataclass, field
from typing import Optional


@dataclass
class ValidationResult:
    """A single validation finding."""

    table: str
    record_index: int
    severity: str  # "error", "warning", "info"
    rule: str
    message: str
    field: Optional[str] = None
