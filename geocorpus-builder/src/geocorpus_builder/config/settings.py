"""GeoCorpus project configuration model."""

from pathlib import Path
from typing import Optional

from pydantic import BaseModel, Field


class TablePaths(BaseModel):
    """Configurable table paths within a project."""

    glacier_yearly_stats: str = "statistics/glacier_yearly_stats.parquet"
    glacier_change_stats: str = "statistics/glacier_change_stats.parquet"
    glacier_grid_crosswalk: str = "statistics/glacier_grid_crosswalk.parquet"
    glacier_neighbor_index: str = "statistics/glacier_neighbor_index.parquet"
    region_summary: str = "statistics/region_summary.parquet"


class GeoCorpusSettings(BaseModel):
    """Project configuration stored in geocorpus_config.yaml."""

    version: str = "0.1"
    domain: str = "cryosphere"
    subdomain: str = "glacier"
    language: str = "zh"
    build_profile: str = "glacier"
    data_dir: str = "data"
    corpus_dir: str = "corpus"
    evidence_dir: str = "evidence"
    templates_dir: str = "templates"
    tables: TablePaths = Field(default_factory=TablePaths)
