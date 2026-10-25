"""Data I/O: read and write corpus data files."""

import json
from pathlib import Path

import pandas as pd


def read_table(path: Path) -> pd.DataFrame:
    """Read a data table from parquet, csv, or json based on file extension."""
    suffix = path.suffix.lower()
    if suffix == ".parquet":
        return pd.read_parquet(path)
    elif suffix == ".csv":
        return pd.read_csv(path)
    elif suffix == ".json":
        return pd.read_json(path)
    else:
        raise ValueError(f"Unsupported table format: {suffix}")


def read_jsonl(path: Path) -> list[dict]:
    """Read a JSONL file, returning a list of parsed dicts."""
    records = []
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                records.append(json.loads(line))
    return records


def read_json(path: Path) -> dict | list:
    """Read a JSON file, returning a dict or list."""
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def read_text(path: Path) -> str:
    """Read a plain text file."""
    with open(path, "r", encoding="utf-8") as f:
        return f.read()
