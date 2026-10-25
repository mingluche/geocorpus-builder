"""Synthetic, independent controlled checks of the unmodified GeoCorpus software."""

from __future__ import annotations

import contextlib
import argparse
import hashlib
import importlib.metadata
import io
import json
import math
import platform
import re
import sys
import time
import traceback
from collections import Counter
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path

sys.dont_write_bytecode = True
WORKSPACE = Path(__file__).resolve().parents[3]
REPO = WORKSPACE / "geocorpus-builder"
sys.path.insert(0, str(REPO / "src"))

import geopandas as gpd
import numpy as np
import pandas as pd
import rasterio
from rasterio.transform import from_origin
from shapely.geometry import Point, Polygon, box

from geocorpus_builder.builder.engine import BuildOrchestrator
from geocorpus_builder.config.project import GeoCorpusProject
from geocorpus_builder.config.settings import GeoCorpusSettings
from geocorpus_builder.spatial.engine import SpatialQueryEngine

STATS = ["mean", "median", "std", "min", "max", "count", "sum"]


def clean(value):
    if isinstance(value, dict):
        return {str(k): clean(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [clean(v) for v in value]
    if isinstance(value, (float, np.floating)):
        return float(value) if math.isfinite(value) else None
    if isinstance(value, (np.integer,)):
        return int(value)
    if isinstance(value, (np.bool_,)):
        return bool(value)
    if isinstance(value, Path):
        return str(value)
    return value


def save_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(clean(value), indent=2, ensure_ascii=False,
                               allow_nan=False), encoding="utf-8")


def load_jsonl(path):
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()
            if line.strip()]


def source_hashes():
    return {str(p.relative_to(REPO)): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in sorted((REPO / "src").rglob("*.py"))}


def finite(value):
    try:
        return math.isfinite(float(value))
    except (TypeError, ValueError):
        return False


def equal_value(left, right, atol=1e-12):
    if finite(left) and finite(right):
        return math.isclose(float(left), float(right), rel_tol=1e-12, abs_tol=atol)
    return not finite(left) and not finite(right)


def independent_reference(array, geom, effective_nodata):
    # Explicit cell centers and Shapely membership; no rasterio mask/rasterize.
    selected = []
    for row in range(10):
        for col in range(10):
            if geom.contains(Point(col + 0.5, 10 - row - 0.5)):
                value = float(array[row, col])
                if math.isfinite(value) and not (
                    effective_nodata is not None
                    and not math.isnan(effective_nodata)
                    and value == effective_nodata
                ):
                    selected.append((row, col, value))
    if not selected:
        return {stat: None for stat in STATS}, selected
    values = np.array([cell[2] for cell in selected], dtype=np.float64)
    result = {
        "mean": float(np.mean(values, dtype=np.float64)),
        "median": float(np.median(values)),
        "std": float(np.std(values, dtype=np.float64, ddof=0)),
        "min": float(np.min(values)), "max": float(np.max(values)),
        "count": int(values.size), "sum": float(np.sum(values, dtype=np.float64)),
    }
    return result, selected


def run_zonal(root):
    folder = root / "zonal"
    folder.mkdir(parents=True)
    polygons = {
        "full_aligned": box(0, 0, 10, 10),
        "sub_aligned": box(1, 1, 4, 4),
        "cross_cell_edges": box(1.2, 1.2, 4.2, 4.2),
        "partial_outside_extent": box(-2, 7, 2.2, 12),
        "outside_extent": box(11, 11, 12, 12),
        "touch_extent_only": box(10, 2, 12, 5),
        "inside_without_cell_center": box(2.1, 2.1, 2.4, 5.9),
        "triangle_partial_cells": Polygon([(1.13, 1.17), (7.87, 1.17), (1.13, 7.91)]),
    }
    vector_path = folder / "synthetic_polygons.geojson"
    gpd.GeoDataFrame({"region_id": list(polygons)}, geometry=list(polygons.values()),
                     crs="EPSG:4326").to_file(vector_path, driver="GeoJSON")
    positive = np.arange(1, 101, dtype=np.float32).reshape(10, 10)
    signed = np.arange(-50, 50, dtype=np.float32).reshape(10, 10)
    nan_array = positive.copy()
    nan_array[2:4, 2:4] = np.nan
    sentinel = positive.copy()
    sentinel[2:4, 2:4] = -9999
    signed_sentinel = signed.copy()
    signed_sentinel[2:4, 2:4] = -9999
    signed_sentinel[5, 5] = np.nan
    variants = [
        ("positive_no_nodata", positive, None, None),
        ("signed_zero_no_nodata", signed, None, None),
        ("all_zero_no_nodata", np.zeros((10, 10), dtype=np.float32), None, None),
        ("nan_no_nodata", nan_array, None, None),
        ("nan_declared_nodata", nan_array, np.nan, None),
        ("sentinel_declared_nodata", sentinel, -9999.0, None),
        ("signed_nan_sentinel", signed_sentinel, -9999.0, None),
        ("sentinel_explicit_override", sentinel, None, -9999.0),
        ("float32_precision", (1e6 + positive / 4).astype(np.float32), -9999.0, None),
    ]
    engine = SpatialQueryEngine(data_dir=folder / "empty_registry")
    comparisons, cases, run_logs, errors = [], [], [], []
    for name, array, header_nodata, override in variants:
        raster_path = folder / f"synthetic_{name}.tif"
        with rasterio.open(raster_path, "w", driver="GTiff", height=10, width=10,
                           count=1, dtype="float32", crs="EPSG:4326",
                           transform=from_origin(0, 10, 1, 1), nodata=header_nodata) as dst:
            dst.write(array, 1)
        pd.DataFrame(array).to_csv(folder / f"reference_array_{name}.csv", index=False)
        output = folder / f"raw_observed_{name}.csv"
        log = io.StringIO()
        start = time.perf_counter()
        try:
            with contextlib.redirect_stdout(log):
                engine.zonal_stats(raster_path, vector_path, output, id_field="region_id",
                                   stats_list=STATS, nodata=override)
            observed = pd.read_csv(output).set_index("region_id")
        except Exception as exc:
            errors.append({"variant": name, "error": repr(exc),
                           "traceback": traceback.format_exc()})
            observed = pd.DataFrame()
        run_logs.append({"variant": name, "elapsed_seconds": time.perf_counter() - start,
                         "stdout": log.getvalue(), "raw_csv": str(output)})
        effective = override if override is not None else header_nodata
        for case_name, geom in polygons.items():
            expected, selected = independent_reference(array, geom, effective)
            obs = observed.loc[case_name].to_dict() if case_name in observed.index else {}
            case_passes = []
            for stat in STATS:
                raw = expected[stat]
                target = None if raw is None else (raw if stat == "count" else round(raw, 4))
                actual = obs.get(stat)
                if raw is None:
                    passed = actual is None or pd.isna(actual)
                    error = None
                elif not finite(actual):
                    passed, error = False, None
                elif stat == "count":
                    passed, error = int(actual) == raw, float(actual) - raw
                else:
                    error = float(actual) - raw
                    passed = math.isclose(float(actual), target, abs_tol=5e-5,
                                          rel_tol=1e-12)
                case_passes.append(passed)
                comparisons.append({
                    "data_kind": "synthetic", "variant": name, "polygon": case_name,
                    "statistic": stat, "reference_raw_float64": raw,
                    "reference_rounded_4dp": target, "observed": actual,
                    "error_from_unrounded_reference": error, "pass": passed,
                    "reference_valid_pixel_count": len(selected),
                    "header_nodata": header_nodata, "explicit_override": override,
                })
            cases.append({"variant": name, "polygon": case_name,
                          "wkt": geom.wkt, "expected": expected, "observed": obs,
                          "reference_cells_row_col_value": selected,
                          "all_statistics_pass": all(case_passes),
                          "centroid_metadata_present": finite(obs.get("lon"))
                          and finite(obs.get("lat")),
                          "variable_metadata_present": isinstance(obs.get("variable"), str)})
    pd.DataFrame(comparisons).to_csv(root / "controlled_zonal_comparison.csv", index=False)
    save_json(root / "controlled_zonal_cases.json", cases)
    save_json(root / "controlled_zonal_run_logs.json", run_logs)
    failed = [row for row in comparisons if not row["pass"]]
    return {"variants": len(variants), "polygons_per_variant": len(polygons),
            "cases": len(cases), "comparisons": len(comparisons),
            "passed_comparisons": len(comparisons) - len(failed),
            "failed_comparisons": len(failed),
            "cases_all_statistics_pass": sum(c["all_statistics_pass"] for c in cases),
            "failed_by_variant": dict(Counter(r["variant"] for r in failed)),
            "failed_by_statistic": dict(Counter(r["statistic"] for r in failed)),
            "cases_missing_centroid_metadata": sum(not c["centroid_metadata_present"] for c in cases),
            "cases_missing_variable_metadata": sum(not c["variable_metadata_present"] for c in cases),
            "errors": errors}


def prepare_project(root, name, rows, extension="csv"):
    project_dir = root / "build" / name
    stats_dir = project_dir / "statistics"
    stats_dir.mkdir(parents=True)
    path = stats_dir / f"controlled_{name}.{extension}"
    frame = pd.DataFrame(rows)
    if extension == "csv":
        frame.to_csv(path, index=False)
    else:
        frame.to_parquet(path, index=False)
    project = GeoCorpusProject(project_dir, GeoCorpusSettings(build_profile="auto"))
    return project, path


def execute_build(project, output, orchestrator=None):
    log = io.StringIO()
    start = time.perf_counter()
    error = None
    report = None
    try:
        with contextlib.redirect_stdout(log):
            report = (orchestrator or BuildOrchestrator(project)).build(
                output=output, spatial_enrich=False, id_prefix="SYN_CONTROLLED")
    except Exception as exc:
        error = {"exception": repr(exc), "traceback": traceback.format_exc()}
    return {"report": asdict(report) if report else None, "error": error,
            "elapsed_seconds": time.perf_counter() - start, "stdout": log.getvalue()}, (
        load_jsonl(output / "corpus" / "corpus_units.jsonl")), (
        load_jsonl(output / "evidence" / "evidence_links.jsonl"))


def audit_build(name, rows, path, units, evidence):
    checks = []
    ev_map = {e["evidence_id"]: e for e in evidence}
    id_field = "region_id" if "region_id" in rows[0] else "object_id"
    stat_fields = [k for k in rows[0] if k in STATS]
    variable_fields = [] if stat_fields else ["temperature", "precipitation"]
    fields = stat_fields or variable_fields
    expected_finite = sum(finite(row.get(field)) for row in rows for field in fields)
    result_units = [u for u in units if u.get("text_type") == "result"]
    mandatory = ["corpus_id", "text", "text_type", "domain", "subdomain",
                 "geo_object_type", "geo_object_id", "spatial_scale", "time_range",
                 "variable", "claim_type", "evidence_ids", "confidence", "source"]
    for unit in result_units:
        links = [ev_map[eid] for eid in unit.get("evidence_ids", []) if eid in ev_map]
        ev = links[0] if links else {}
        field = ev.get("statistic")
        candidates = [r for r in rows if str(r.get(id_field)) == unit.get("geo_object_id")]
        candidates_by_value = [r for r in candidates if equal_value(r.get(field), ev.get("value"))]
        row = candidates_by_value[0] if len(candidates_by_value) == 1 else (candidates[0] if candidates else {})
        expected_value = row.get(field)
        match = re.search(r"\u4e3a([+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:e[+-]?\d+)?|nan|inf)(.*?)\uff08\u6765\u6e90", unit.get("text", ""), re.I)
        text_value = match.group(1) if match else None
        expected_variable = field if variable_fields else row.get("variable", path.stem)
        checks.append({
            "data_kind": "synthetic", "build_case": name,
            "corpus_id": unit.get("corpus_id"), "geo_object_id": unit.get("geo_object_id"),
            "source_field": field, "expected_value": expected_value,
            "observed_evidence_value": ev.get("value"), "observed_text_value": text_value,
            "input_value_finite": finite(expected_value),
            "evidence_value_matches_input": finite(expected_value) and equal_value(expected_value, ev.get("value")),
            "text_value_matches_input": finite(expected_value) and equal_value(expected_value, text_value),
            "internal_text_evidence_consistent": text_value is not None and equal_value(text_value, ev.get("value")),
            "source_id_matches": ev.get("source_id") == str(row.get(id_field)),
            "source_table_matches": ev.get("source_table") == path.stem,
            "variable_matches": unit.get("variable") == expected_variable,
            "time_matches_row": str(unit.get("time_range")) == str(row.get("time_range")),
            "coordinates_match_row": all(equal_value(unit.get(k), row.get(k)) for k in ("lon", "lat") if k in row),
            "required_keys_present": all(k in unit for k in mandatory),
            "one_existing_evidence_link": len(links) == 1 and len(unit.get("evidence_ids", [])) == 1,
            "evidence_backlink_matches": ev.get("corpus_id") == unit.get("corpus_id"),
            "unresolved_placeholder": bool(re.search(r"\$\{[^}]+\}", unit.get("text", ""))),
            "text": unit.get("text", ""),
        })
    referenced = {eid for u in units for eid in u.get("evidence_ids", [])}
    summary = {
        "case": name, "input_format": path.suffix, "input_rows": len(rows),
        "expected_finite_result_facts": expected_finite, "observed_result_units": len(result_units),
        "total_units_including_derived": len(units), "evidence_records": len(evidence),
        "duplicate_corpus_ids": len(units) - len({u["corpus_id"] for u in units}),
        "duplicate_evidence_ids": len(evidence) - len(ev_map),
        "dangling_evidence_references": len(referenced - set(ev_map)),
        "unreferenced_evidence_records": len(set(ev_map) - referenced),
        "invalid_numeric_result_units": sum(not c["input_value_finite"] for c in checks),
        "checks": {key: {"pass": sum(bool(c[key]) for c in checks), "denominator": len(checks)}
                   for key in ["evidence_value_matches_input", "text_value_matches_input",
                               "internal_text_evidence_consistent", "source_id_matches",
                               "source_table_matches", "variable_matches", "time_matches_row",
                               "coordinates_match_row", "required_keys_present",
                               "one_existing_evidence_link", "evidence_backlink_matches"]},
    }
    return summary, checks


def run_builds(root):
    rows = [{"region_id": f"SYN_R{i}", "mean": value, "time_range": "2020",
             "variable": "controlled_temperature", "lon": 100.0 + i, "lat": 30.0 + i}
            for i, value in enumerate([-2.5, 0.0, 1.25, float("nan")])]
    generic_rows = [{"object_id": f"SYN_CUSTOM{i}", "mean": float(value),
                     "time_range": "2020", "variable": "controlled_temperature"}
                    for i, value in enumerate([3, 7])]
    time_rows = [{"region_id": "SYN_SAME", "mean": value, "time_range": year,
                  "variable": "controlled_temperature"}
                 for value, year in [(1.0, "2020"), (2.0, "2021")]]
    zero_rows = [{"region_id": f"SYN_ZERO{i}", "mean": 0.0, "time_range": "2020",
                  "variable": "controlled_temperature"} for i in range(2)]
    multi_rows = [{"region_id": f"SYN_MULTI{i}", "temperature": temp,
                   "precipitation": precip, "time_range": "2020"}
                  for i, (temp, precip) in enumerate([(-4.5, 0.0), (2.0, 12.0)])]
    fixtures = [("stat_csv", rows, "csv"), ("stat_parquet", rows, "parquet"),
                ("custom_object_id", generic_rows, "csv"),
                ("per_row_time", time_rows, "csv"), ("zero_pair", zero_rows, "csv"),
                ("multi_variable", multi_rows, "parquet")]
    summaries, checks = [], []
    for name, data, extension in fixtures:
        project, path = prepare_project(root, name, data, extension)
        run, units, evidence = execute_build(project, project.root)
        summary, current_checks = audit_build(name, data, path, units, evidence)
        summary.update(run)
        summaries.append(summary)
        checks.extend(current_checks)
    # Exercise the public build method twice on one object without changing source.
    repeat_rows = [{"region_id": "SYN_REPEAT", "mean": 10.0, "time_range": "2020",
                    "variable": "controlled_temperature"}]
    project, path = prepare_project(root, "repeat_same_orchestrator", repeat_rows)
    orchestrator = BuildOrchestrator(project)
    repeat_runs = []
    for iteration in [1, 2]:
        run, units, evidence = execute_build(project, project.root, orchestrator)
        summary, current_checks = audit_build("repeat_same_orchestrator", repeat_rows,
                                              path, units, evidence)
        summary.update(run)
        summary["iteration"] = iteration
        repeat_runs.append(summary)
    # Separate input datasets, one destination, unchanged public default ID behavior.
    append_runs = []
    common_output = root / "build" / "append_shared_destination"
    for iteration, value in [(1, 10.0), (2, 20.0)]:
        data = [{"region_id": f"SYN_APPEND{iteration}", "mean": value,
                 "time_range": "2020", "variable": "controlled_temperature"}]
        project, path = prepare_project(root, f"append_dataset{iteration}", data)
        run, units, evidence = execute_build(project, common_output)
        append_runs.append({"iteration": iteration, "expected_new_object": data[0]["region_id"],
                            "observed_objects": [u.get("geo_object_id") for u in units],
                            "new_object_present": any(u.get("geo_object_id") == data[0]["region_id"] for u in units),
                            "total_units": len(units), "total_evidence": len(evidence), **run})
    pd.DataFrame(checks).to_csv(root / "controlled_build_checks.csv", index=False)
    save_json(root / "controlled_build_cases.json", summaries)
    save_json(root / "controlled_build_lifecycle.json", {
        "repeat_same_orchestrator": repeat_runs, "append_same_prefix": append_runs})
    return {"isolated_build_cases": summaries, "repeat_same_orchestrator": repeat_runs,
            "append_same_prefix": append_runs}


def protocol_comparison(root):
    """Re-score retained raw values; do not invoke or change tested software."""
    frame = pd.read_csv(root / "controlled_zonal_comparison.csv")
    rows = []
    for original in frame.to_dict("records"):
        expected = original["reference_raw_float64"]
        observed = original["observed"]
        if pd.isna(expected):
            passed = pd.isna(observed)
            threshold = None
        elif not finite(observed):
            passed = False
            threshold = 0 if original["statistic"] == "count" else 5e-5 + 1e-6 * abs(expected)
        elif original["statistic"] == "count":
            passed = observed == expected
            threshold = 0
        else:
            threshold = 5e-5 + 1e-6 * abs(expected)
            passed = abs(observed - expected) <= threshold
        rows.append({**original, "strict_diagnostic_pass": original["pass"],
                     "chapter3_protocol_threshold": threshold,
                     "chapter3_protocol_pass": passed})
    result = pd.DataFrame(rows)
    path = root / "controlled_protocol_comparison.csv"
    result.to_csv(path, index=False)

    def totals(subset):
        failed = subset[~subset["chapter3_protocol_pass"]]
        groups = subset.groupby(["variant", "polygon"])["chapter3_protocol_pass"].all()
        return {"passed": int(subset["chapter3_protocol_pass"].sum()),
                "denominator": len(subset), "failed": len(failed),
                "cases_all_pass": int(groups.sum()), "case_denominator": len(groups),
                "failed_by_variant": failed.groupby("variant").size().to_dict(),
                "failed_by_statistic": failed.groupby("statistic").size().to_dict()}

    summary = {
        "data_kind": "synthetic_only", "source_run": str(root),
        "operation": "postprocess_only_no_tested_software_rerun",
        "postprocess_script_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        "raw_comparison_csv_sha256": hashlib.sha256((root / "controlled_zonal_comparison.csv").read_bytes()).hexdigest(),
        "primary_predeclared_chapter3_rule": "abs(observed-unrounded_float64_reference) <= 5e-5 + 1e-6*abs(reference); count exact; empty statistics null",
        "strict_diagnostic_rule": "original reference rounded to 4dp, abs_tol=5e-5 and rel_tol=1e-12; retained separately",
        "main_six_statistics": totals(result[result["statistic"] != "sum"]),
        "main_six_finite_reference": totals(result[(result["statistic"] != "sum") & result["reference_raw_float64"].notna()]),
        "main_six_empty_reference": totals(result[(result["statistic"] != "sum") & result["reference_raw_float64"].isna()]),
        "controlled_extension_sum": totals(result[result["statistic"] == "sum"]),
        "all_seven_statistics": totals(result),
        "strict_original_main_six": {"passed": int(result.loc[result["statistic"] != "sum", "pass"].sum()),
                                     "denominator": int((result["statistic"] != "sum").sum())},
        "comparison_csv": str(path),
        "build_audit_scope_notes": [
            "Numeric semantic checks cover result units, not complete semantic review of derived interpretation/comparison units.",
            "Coordinate correctness is only tested where lon/lat are provided: stat_csv and stat_parquet, eight result units. Other coordinate check booleans were vacuous and are not evidence of coordinate accuracy.",
            "Zero-pair build failure must retain input-side denominator two; zero output is not a successful zero-denominator numeric evaluation.",
            "No manual validation or real-data claim is made.",
        ],
        "reproduce_command": f'& "{sys.executable}" "{Path(__file__).resolve()}" --protocol-only "{root}"',
    }
    save_json(root / "controlled_protocol_summary.json", summary)
    return summary


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--protocol-only", type=Path)
    arguments = parser.parse_args()
    if arguments.protocol_only:
        print(json.dumps(clean(protocol_comparison(arguments.protocol_only.resolve())), indent=2))
        return 0
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    root = Path(__file__).resolve().parents[1] / "results" / f"controlled_{stamp}"
    root.mkdir(parents=True)
    before = source_hashes()
    summary = {
        "data_kind": "synthetic_only", "human_validation": False,
        "started_utc": stamp, "output_dir": root, "python": sys.executable,
        "python_version": sys.version, "platform": platform.platform(),
        "tested_repository": REPO, "script_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        "package_versions": {name: importlib.metadata.version(name) for name in
                             ["numpy", "pandas", "geopandas", "rasterio", "shapely", "pyarrow", "pydantic"]},
        "reference_protocol": {
            "grid": "synthetic float32 10x10, EPSG:4326, extent(0,0,10,10), pixel size 1",
            "selection": "strict Shapely contains on explicit pixel centers; no center lies on tested polygon boundary",
            "validity": "finite cells, excluding effective declared/explicit nodata",
            "statistics": "independent NumPy float64 reductions; population std ddof=0",
            "comparison": "reference rounded to 4dp; abs_tol=5e-5, rel_tol=1e-12; count exact",
            "empty_zone_contract": "all statistics null, including count, matching current source-code empty-result convention; reference selected-cell count recorded separately",
            "timing": "single diagnostic run per fixture; not a performance benchmark",
            "build": "unmodified auto build profile, default post-build enrichment retained, spatial_enrich=False",
        },
        "reproduce_command": f'& "{sys.executable}" "{Path(__file__).resolve()}"',
    }
    try:
        summary["zonal"] = run_zonal(root)
        summary["build"] = run_builds(root)
        summary["chapter3_protocol"] = protocol_comparison(root)
    except Exception as exc:
        summary["harness_fatal_error"] = {"exception": repr(exc), "traceback": traceback.format_exc()}
    summary["source_hashes_before"] = before
    summary["source_hashes_after"] = source_hashes()
    summary["source_files_unchanged"] = before == summary["source_hashes_after"]
    save_json(root / "controlled_summary.json", summary)
    print(json.dumps(clean({"output_dir": root, "zonal": summary.get("zonal"),
                           "build_cases": [{"case": c["case"], "expected_finite_result_facts": c["expected_finite_result_facts"],
                                            "observed_result_units": c["observed_result_units"],
                                            "invalid_numeric_result_units": c["invalid_numeric_result_units"],
                                            "error": c["error"], "checks": c["checks"]}
                                           for c in summary.get("build", {}).get("isolated_build_cases", [])],
                           "source_files_unchanged": summary["source_files_unchanged"],
                           "harness_fatal_error": summary.get("harness_fatal_error")}), indent=2))
    return 1 if summary.get("harness_fatal_error") else 0


if __name__ == "__main__":
    raise SystemExit(main())
