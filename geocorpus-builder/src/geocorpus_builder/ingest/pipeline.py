"""Data ingestion pipeline: raster/vector/crosswalk -> evidence_links."""

import csv
from pathlib import Path
from typing import Optional

import pandas as pd


def ingest_raster_zonal_stats(
    stats_path: Path,
    output_path: Path,
    zone_field: str = "glacier_id",
    variable: str = "glacier_thickness",
    time_range: str = "",
    id_prefix: str = "EV_RS",
) -> list[dict]:
    """Read raster zonal statistics and create evidence_links.

    Expects a CSV or Parquet with columns for the zone ID and statistics.
    """
    df = _read_any(stats_path)
    evidence = _df_to_evidence(df, zone_field, variable, time_range,
                                id_prefix, "raster", str(stats_path.name))
    _write_jsonl(evidence, output_path)
    print(f"Ingested {len(evidence)} evidence links from raster zonal stats: {stats_path.name}")
    return evidence


def ingest_vector_attributes(
    vector_path: Path,
    output_path: Path,
    id_field: str = "glacier_id",
    variable: str = "glacier_thickness",
    time_range: str = "",
    id_prefix: str = "EV_VEC",
) -> list[dict]:
    """Read vector attribute table and create evidence_links."""
    df = _read_any(vector_path)
    evidence = _df_to_evidence(df, id_field, variable, time_range,
                                id_prefix, "vector", str(vector_path.name))
    _write_jsonl(evidence, output_path)
    print(f"Ingested {len(evidence)} evidence links from vector attributes: {vector_path.name}")
    return evidence


def ingest_crosswalk(
    crosswalk_path: Path,
    output_path: Path,
    id_prefix: str = "EV_CW",
) -> list[dict]:
    """Read object-grid crosswalk table and create evidence_links."""
    df = _read_any(crosswalk_path)
    evidence: list[dict] = []
    counter = 0

    for _, row in df.iterrows():
        row_dict = row.to_dict()
        counter += 1
        evidence.append({
            "evidence_id": f"{id_prefix}_{counter:04d}",
            "corpus_id": None,
            "evidence_type": "crosswalk",
            "source_table": str(crosswalk_path.name),
            "source_id": str(row_dict.get("object_id", row_dict.get("glacier_id", ""))),
            "variable": "area_weight",
            "statistic": "weight",
            "value": row_dict.get("area_fraction", row_dict.get("weight", None)),
            "unit": None,
            "time_range": row_dict.get("time_range", ""),
            "spatial_scale": "object_grid",
            "notes": f"Crosswalk record linking {row_dict.get('object_id', '?')} to grid",
        })

    _write_jsonl(evidence, output_path)
    print(f"Ingested {len(evidence)} evidence links from crosswalk: {crosswalk_path.name}")
    return evidence


def _read_any(path: Path) -> pd.DataFrame:
    suffix = path.suffix.lower()
    if suffix == ".parquet":
        return pd.read_parquet(path)
    elif suffix == ".csv":
        return pd.read_csv(path)
    elif suffix == ".json":
        return pd.read_json(path)
    else:
        raise ValueError(f"Unsupported format: {suffix}")


def _df_to_evidence(df: pd.DataFrame, id_field: str, variable: str,
                    time_range: str, id_prefix: str, evidence_type: str,
                    source_table: str) -> list[dict]:
    evidence: list[dict] = []
    counter = 0
    stat_cols = _detect_stat_columns(df, id_field)

    for _, row in df.iterrows():
        row_dict = row.to_dict()
        source_id = str(row_dict.get(id_field, ""))
        if not source_id:
            continue

        for col in stat_cols:
            val = row_dict.get(col)
            if val is None or (isinstance(val, float) and pd.isna(val)):
                continue
            counter += 1
            evidence.append({
                "evidence_id": f"{id_prefix}_{counter:04d}",
                "corpus_id": None,
                "evidence_type": evidence_type,
                "source_table": source_table,
                "source_id": source_id,
                "variable": variable,
                "statistic": col,
                "value": str(val),
                "unit": "",
                "time_range": time_range,
                "spatial_scale": "object",
                "notes": "",
            })
    return evidence


def _detect_stat_columns(df: pd.DataFrame, id_field: str) -> list[str]:
    """Auto-detect numeric statistic columns (exclude ID, year, etc.)."""
    exclude = {id_field, "year", "time_range", "variable",
               "object_id", "grid_id", "region_id", "glacier_id"}
    numeric_cols = df.select_dtypes(include="number").columns.tolist()
    return [c for c in numeric_cols if c not in exclude]


def _write_jsonl(records: list[dict], path: Path) -> None:
    import json
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        for record in records:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")
