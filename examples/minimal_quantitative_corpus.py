"""API-free demonstration using explicitly synthetic, non-observational values."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import pandas as pd
from geocorpus_builder.builder.engine import BuildOrchestrator
from geocorpus_builder.config.project import GeoCorpusProject
from geocorpus_builder.io import read_jsonl


def run(output: Path):
    if output.exists():
        raise FileExistsError("Use a new output directory; existing results are never removed.")
    project = GeoCorpusProject.init(output, domain="geomorphology", subdomain="synthetic_demo")
    rows = [{"region_id": "FICTIONAL_A", "variable": "elevation_demo", "time_range": "static",
             "mean": 1200.0, "count": 4},
            {"region_id": "FICTIONAL_B", "variable": "elevation_demo", "time_range": "static",
             "mean": 1800.0, "count": 6}]
    pd.DataFrame(rows).to_csv(output / "statistics/demo_elevation.csv", index=False)
    (output / "templates/generic_stat.txt").write_text(
        "{geo_object_id}: {variable} {statistic} = {value} ({time_range}).", encoding="utf-8")
    report = BuildOrchestrator(project).build(id_prefix="DEMO")
    if report.errors:
        raise AssertionError(report.errors)
    units = read_jsonl(output / "corpus/corpus_units.jsonl")
    evidence = read_jsonl(output / "evidence/evidence_links.jsonl")
    index = {e["evidence_id"]: e for e in evidence}
    basic = [u for u in units if u["text_type"] == "result"]
    assert len(basic) == 4 and len(evidence) == 4
    expected = {(r["region_id"], s): r[s] for r in rows for s in ["mean", "count"]}
    for unit in basic:
        assert len(unit["evidence_ids"]) == 1
        ev = index[unit["evidence_ids"][0]]
        assert ev["source_id"] == unit["geo_object_id"]
        assert float(ev["value"]) == expected[(ev["source_id"], ev["statistic"])]
    summary = {"input_kind": "synthetic demonstration; not environmental observations",
               "basic_records": len(basic), "derived_records": len(units)-len(basic),
               "evidence_records": len(evidence), "basic_numeric_links_verified": True,
               "physical_unit_metadata_empty": sum(not e.get("unit") for e in evidence),
               "llm_api_required": False}
    (output / "demo_checks.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    return summary


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    print(json.dumps(run(parser.parse_args().output.resolve()), indent=2))
