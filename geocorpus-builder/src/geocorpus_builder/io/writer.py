"""Data I/O: write corpus data to files."""

import json
from pathlib import Path

import pandas as pd


def write_jsonl(records: list[dict], path: Path) -> None:
    """Write a list of records as JSONL, one JSON object per line."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        for record in records:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")


def write_csv(records: list[dict], path: Path) -> None:
    """Write a list of dict records as CSV via pandas."""
    path.parent.mkdir(parents=True, exist_ok=True)
    df = pd.DataFrame(records)
    df.to_csv(path, index=False)


def write_parquet(df: pd.DataFrame, path: Path) -> None:
    """Write a DataFrame as Parquet."""
    path.parent.mkdir(parents=True, exist_ok=True)
    df.to_parquet(path, index=False)


def write_json(data: dict | list, path: Path) -> None:
    """Write data as indented JSON."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
