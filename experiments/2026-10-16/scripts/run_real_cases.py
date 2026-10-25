"""Reproducible, unmodified-GeoCorpus three-path experiment.

The independent reference reads raster cells with rasterio, but does not use
rasterio.mask, rasterstats, or any GeoCorpus statistics function. Pixel-centre
selection is performed by Shapely; moments use NumPy float64 and ddof=0.
"""

from __future__ import annotations

import argparse
import contextlib
import hashlib
import importlib.metadata
import json
import math
import platform
import re
import sys
import time
import traceback
from pathlib import Path

import geopandas as gpd
import numpy as np
import pandas as pd
import rasterio
from rasterio.transform import from_origin
from rasterio.windows import Window
from shapely import contains_xy, intersects_xy, prepare
from shapely.geometry import box

WORKSPACE = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(WORKSPACE / "geocorpus-builder" / "src"))

from geocorpus_builder.builder.engine import BuildOrchestrator
from geocorpus_builder.config.project import GeoCorpusProject
from geocorpus_builder.config.settings import GeoCorpusSettings
from geocorpus_builder.io import read_jsonl
from geocorpus_builder.spatial.engine import SpatialQueryEngine
from geocorpus_builder.spatial.registry import LayerMeta

STATS = ("mean", "median", "std", "min", "max", "count")
KEY = ("region_id", "variable", "statistic", "time_range")
NUMBER = r"[+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?|[+-]?(?:nan|inf)"
SEMANTICS = {
    "reference_selection": "strict polygon interior at raster pixel centres",
    "boundary_tie": "centre intersects polygon but is not strictly contained",
    "boundary_tie_handling": "report strict and boundary-inclusive references separately; do not discard tied regions",
    "software_selection": "original rasterio.mask.mask default all_touched=False; no override",
    "nodata": "exclude raster nodata and NaN; report outside-raster coverage separately",
    "band": 1,
    "weighting": "equal cell weights, not area weighting",
    "reference_dtype": "float64",
    "std_ddof": 0,
    "rounding": "four decimal places for non-count statistics; integer count",
    "numeric_stat_tolerance": "abs_error <= 5e-5 + 1e-6 * abs(float64 reference); count exact",
    "absolute_tolerance": 5e-5,
    "relative_tolerance": 1e-6,
    "strict_rounding_diagnostic_tolerance": 0.0000500001,
    "text_to_evidence_tolerance": "1e-10 * max(1, abs(evidence value))",
    "value_space": "raw stored raster values; scales and offsets are recorded, not applied",
    "human_review": "not performed by this runner",
}


def clean_json(value):
    if isinstance(value, dict):
        return {str(k): clean_json(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [clean_json(v) for v in value]
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, (np.integer,)):
        return int(value)
    if isinstance(value, (float, np.floating)):
        return float(value) if math.isfinite(float(value)) else None
    if isinstance(value, np.bool_):
        return bool(value)
    return value


def write_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(clean_json(value), ensure_ascii=False, indent=2,
                               allow_nan=False), encoding="utf-8")


def write_csv(path, rows):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    df = rows if isinstance(rows, pd.DataFrame) else pd.DataFrame(rows)
    df.to_csv(path, index=False, encoding="utf-8-sig")


def file_hash(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def load_manifest(manifest):
    if isinstance(manifest, dict):
        return manifest
    path = Path(manifest).resolve()
    data = json.loads(path.read_text(encoding="utf-8"))
    data["manifest_path"] = str(path)
    for item in [data["vector"], *data.get("rasters", [])]:
        item["path"] = str((path.parent / item["path"]).resolve())
    if "rasters" not in data or not data["rasters"]:
        raise ValueError("Manifest must contain at least one raster")
    names = [r["variable"] for r in data["rasters"]]
    if len(names) != len(set(names)):
        raise ValueError("Raster variable names must be unique; distinguish months/periods explicitly")
    for raster in data["rasters"]:
        raster.setdefault("time_range", "unknown")
        raster.setdefault("unit", "")
    return data


def read_vector(spec):
    path = Path(spec["path"])
    if path.suffix.lower() in (".parquet", ".geoparquet"):
        return gpd.read_parquet(path)
    kwargs = {"layer": spec["layer"]} if spec.get("layer") else {}
    return gpd.read_file(path, **kwargs)


def prepare_samples(manifest, output_dir, seed=2026, n_base=100, n_reuse=100,
                    sample_sizes=(100, 500, 1000)):
    """Export stable nested samples; public interface for run_benchmarks.py.

    prepared_vector.gpkg contains all selected rows in sample_order. The first
    n_base rows are the base cohort; the next n_reuse are disjoint reuse rows.
    Larger samples are prefixes of the same seeded permutation, not resamples.
    """
    manifest = load_manifest(manifest)
    output_dir = Path(output_dir).resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    spec = manifest["vector"]
    raw = read_vector(spec)
    if raw.crs is None:
        raise ValueError("Vector CRS is absent; it must not be guessed")
    id_field = spec["id_field"]
    if id_field not in raw:
        raise ValueError(f"Missing source ID field: {id_field}")
    if raw[id_field].isna().any() or not raw[id_field].is_unique:
        raise ValueError("Source object IDs must be nonmissing and unique")
    valid = raw.geometry.notna() & ~raw.geometry.is_empty & raw.geometry.is_valid
    excluded = [{"source_id": str(row[id_field]), "reason": "missing_empty_or_invalid_geometry"}
                for _, row in raw.loc[~valid].iterrows()]
    pool = raw.loc[valid].copy()
    if spec.get("bbox"):
        extent = box(*spec["bbox"])
        mask = pool.to_crs("EPSG:4326").geometry.intersects(extent)
        excluded += [{"source_id": str(v), "reason": "outside_preregistered_bbox"}
                     for v in pool.loc[~mask, id_field]]
        pool = pool.loc[mask].copy()
    filters = spec.get("filters", {})
    for field, limits in filters.items():
        mask = pd.Series(True, index=pool.index)
        if "min" in limits:
            mask &= pool[field] >= limits["min"]
        if "max" in limits:
            mask &= pool[field] <= limits["max"]
        excluded += [{"source_id": str(v), "reason": f"preregistered_filter:{field}"}
                     for v in pool.loc[~mask, id_field]]
        pool = pool.loc[mask].copy()
    required = max(n_base + n_reuse, *sample_sizes)
    if len(pool) < n_base + n_reuse:
        raise ValueError(f"Only {len(pool)} eligible objects; need {n_base + n_reuse}")
    attributes = spec.get("attributes") or [
        c for c in pool if c not in (id_field, "geometry", spec.get("name_field"))
        and pd.api.types.is_numeric_dtype(pool[c])][:5]
    if not attributes or any(c not in pool for c in attributes):
        raise ValueError("No valid vector attributes specified")
    # Freeze strata before looking at any software/reference outputs. Equal
    # round-robin allocation makes every nested prefix follow the same rule.
    area_field, elevation_field = "SUB_AREA", "ele_mt_sav"
    if area_field not in pool or elevation_field not in pool:
        raise ValueError("Stratified protocol needs SUB_AREA and ele_mt_sav")
    area_bin, area_edges = pd.qcut(pool[area_field], 4, labels=False, retbins=True, duplicates="drop")
    elevation_bin, elevation_edges = pd.qcut(pool[elevation_field], 4, labels=False, retbins=True, duplicates="drop")
    if area_bin.isna().any() or elevation_bin.isna().any():
        raise ValueError("Stratification fields contain missing/unclassifiable values")
    pool["stratum"] = [f"A{int(a)+1}_E{int(e)+1}" for a, e in zip(area_bin, elevation_bin)]
    strata = sorted(pool.stratum.unique())
    rng = np.random.default_rng(seed)
    positions = {name: list(rng.permutation(np.flatnonzero(pool.stratum.to_numpy() == name)))
                 for name in strata}
    order, offsets = [], {name: 0 for name in strata}
    while len(order) < min(required, len(pool)):
        for name in strata:
            if offsets[name] < len(positions[name]):
                order.append(int(positions[name][offsets[name]]))
                offsets[name] += 1
                if len(order) >= min(required, len(pool)):
                    break
    sample = pool.iloc[order].copy().reset_index(drop=True)
    source_ids = sample[id_field].map(str)
    sample["region_id"] = "R_" + source_ids
    if spec.get("name_field"):
        sample["region_name"] = sample[spec["name_field"]].map(str)
    else:
        sample["region_name"] = sample["region_id"]
    sample["sample_order"] = np.arange(len(sample), dtype="int64")
    sample["cohort"] = np.where(sample.sample_order < n_base, "base",
                                 np.where(sample.sample_order < n_base + n_reuse,
                                          "reuse", "nested_only"))
    destination = output_dir / "prepared_vector.gpkg"
    if destination.exists():
        raise FileExistsError(f"Refusing to replace {destination}")
    sample.to_file(destination, layer="samples", driver="GPKG", index=False)
    membership = sample[["region_id", "region_name", "sample_order", "cohort", "stratum",
                         area_field, elevation_field]].copy()
    membership["source_id"] = source_ids
    for size in sample_sizes:
        membership[f"in_first_{size}"] = membership.sample_order < size
    write_csv(output_dir / "sample_membership.csv", membership)
    allocation = []
    for name in strata:
        allocation.append({"stratum": name, "population_count": int((pool.stratum == name).sum()),
                           "base_count": int(((sample.stratum == name) & (sample.cohort == "base")).sum()),
                           "reuse_count": int(((sample.stratum == name) & (sample.cohort == "reuse")).sum()),
                           **{f"first_{size}": int(((sample.stratum == name) & (sample.sample_order < size)).sum())
                              for size in sample_sizes}})
    write_csv(output_dir / "stratum_allocation.csv", allocation)
    write_csv(output_dir / "excluded_objects.csv", excluded)
    result = {
        "prepared_vector": str(destination), "prepared_layer": "samples",
        "manifest": manifest, "attributes": attributes, "seed": seed,
        "source_feature_count": len(raw), "eligible_feature_count": len(pool),
        "source_subset_rule": spec.get("subset_rule"),
        "source_id_first_digit_counts": raw[id_field].map(str).str[0].value_counts().to_dict(),
        "selected_feature_count": len(sample), "requested_nested_sizes": list(sample_sizes),
        "available_nested_sizes": [n for n in sample_sizes if n <= len(sample)],
        "n_base": n_base, "n_reuse": n_reuse,
        "sampling_method": "marginal quartiles SUB_AREA x ele_mt_sav; seed-shuffle within joint strata; fixed sorted-stratum round-robin prefixes",
        "strata_population": allocation, "area_quartile_edges": area_edges.tolist(),
        "elevation_quartile_edges": elevation_edges.tolist(),
        "excluded_object_count": len(excluded), "id_adapter": f"region_id='R_'+str({id_field})",
        "source_vector_sha256": file_hash(spec["path"]) if Path(spec["path"]).is_file() else None,
        "prepared_vector_sha256": file_hash(destination),
    }
    write_json(output_dir / "prepared_manifest.json", result)
    return result


def prepared_frame(prepared, n=None, start=0):
    frame = gpd.read_file(prepared["prepared_vector"], layer=prepared.get("prepared_layer", "samples"))
    frame = frame.sort_values("sample_order").reset_index(drop=True)
    return frame.iloc[start:start + n].copy() if n is not None else frame


def moments(values):
    if not len(values):
        return {stat: (0 if stat == "count" else None) for stat in STATS}
    data = np.asarray(values, dtype="float64")
    return {"mean": float(np.mean(data)), "median": float(np.median(data)),
            "std": float(np.std(data, ddof=0)), "min": float(np.min(data)),
            "max": float(np.max(data)), "count": int(len(data))}


def independent_reference(raster_path, frame, variable, time_range):
    """Return float64 centre-selected reference and a boundary/NoData audit."""
    statistics, diagnostics = [], []
    with rasterio.open(raster_path) as src:
        transform = src.transform
        if transform.b != 0 or transform.d != 0 or transform.a <= 0 or transform.e >= 0:
            raise ValueError("Independent reference currently requires a north-up, unrotated raster")
        if src.crs is None:
            raise ValueError("Raster CRS is absent")
        local = frame.to_crs(src.crs)
        inverse = ~transform
        for _, row in local.iterrows():
            geom = row.geometry
            prepare(geom)
            minx, miny, maxx, maxy = geom.bounds
            left, top = inverse * (minx, maxy)
            right, bottom = inverse * (maxx, miny)
            c0, r0 = max(0, math.floor(left)), max(0, math.floor(top))
            c1, r1 = min(src.width, math.ceil(right)), min(src.height, math.ceil(bottom))
            strict_values = inclusive_values = np.array([], dtype="float64")
            tied_count = strict_count = invalid_count = total = 0
            if c1 > c0 and r1 > r0:
                values = src.read(1, window=Window(c0, r0, c1-c0, r1-r0))
                cols, rows = np.meshgrid(np.arange(c0, c1) + 0.5,
                                          np.arange(r0, r1) + 0.5)
                xs = transform.c + cols * transform.a
                ys = transform.f + rows * transform.e
                strict = contains_xy(geom, xs, ys)
                inclusive = intersects_xy(geom, xs, ys)
                valid = ~pd.isna(values)
                if src.nodata is not None and not pd.isna(src.nodata):
                    valid &= values != src.nodata
                tied_count = int(np.count_nonzero(inclusive & ~strict))
                strict_count = int(np.count_nonzero(strict))
                invalid_count = int(np.count_nonzero(strict & ~valid))
                total = int(values.size)
                strict_values = values[strict & valid].astype("float64")
                inclusive_values = values[inclusive & valid].astype("float64")
            strict_stats = moments(strict_values)
            inclusive_stats = moments(inclusive_values)
            entry = {"region_id": str(row.region_id), "variable": variable,
                     "time_range": str(time_range), **strict_stats}
            statistics.append(entry)
            diagnostics.append({
                "region_id": str(row.region_id), "variable": variable,
                "raster": str(raster_path), "window_cell_count": total,
                "strict_inside_centres": strict_count, "nodata_inside_centres": invalid_count,
                "boundary_tied_centres": tied_count, "valid_cell_count": len(strict_values),
                "no_valid_cells": not bool(len(strict_values)), "stored_dtype": src.dtypes[0],
                "nodata": src.nodata, "scale": src.scales[0], "offset": src.offsets[0],
                **{f"boundary_inclusive_{stat}": value for stat, value in inclusive_stats.items()},
            })
        metadata = {"path": str(raster_path), "sha256": file_hash(raster_path),
                    "crs": str(src.crs), "transform": list(src.transform),
                    "width": src.width, "height": src.height, "count": src.count,
                    "dtype": src.dtypes[0], "nodata": src.nodata,
                    "scales": list(src.scales), "offsets": list(src.offsets),
                    "tags": src.tags(), "band_tags": src.tags(1)}
    return pd.DataFrame(statistics), pd.DataFrame(diagnostics), metadata


def finite(value):
    try:
        return math.isfinite(float(value))
    except (ValueError, TypeError):
        return False


def close(value, expected, tol=1e-10):
    return finite(value) and finite(expected) and abs(float(value)-float(expected)) <= tol * max(1., abs(float(expected)))


def canon_unit(value):
    return str(value or "").strip().lower().replace(" ", "").replace("²", "2").replace("^", "")


def add_failure(failures, stage, error):
    failures.append({"stage": stage, "exception": type(error).__name__,
                     "message": str(error), "traceback": traceback.format_exc()})


def load_outputs(project):
    units = project / "corpus" / "corpus_units.jsonl"
    evidence = project / "evidence" / "evidence_links.jsonl"
    return (read_jsonl(units) if units.exists() else [],
            read_jsonl(evidence) if evidence.exists() else [])


def expected_long(frame, value_columns, variable=None, period=None, unit="", table="", reference=None,
                  unit_map=None, boundary_counts=None):
    expected = []
    refs = reference.set_index("region_id") if reference is not None else None
    for _, row in frame.iterrows():
        for column in value_columns:
            value = row[column]
            if pd.isna(value):
                continue
            var = variable if variable is not None else column
            stat = column if variable is not None else "value"
            raw_reference = refs.loc[str(row.region_id), column] if refs is not None else value
            expected.append({"region_id": str(row.region_id), "variable": str(var),
                             "statistic": stat, "time_range": str(period),
                             "input_value": value, "reference_value": raw_reference,
                             "expected_unit": (unit_map or {}).get(column, unit),
                             "expected_source_table": table,
                             "boundary_tied_centres": (boundary_counts or {}).get(str(row.region_id), 0)})
    return expected


def raster_expected(reference, actual, spec, diagnostics):
    """The denominator comes from the reference, never successful software output."""
    targets = []
    actual_by_id = actual.set_index("region_id") if actual is not None and len(actual) else None
    ties = diagnostics.set_index("region_id").boundary_tied_centres.to_dict()
    for _, row in reference.iterrows():
        rid = str(row.region_id)
        for stat in STATS:
            value = row[stat]
            if pd.isna(value):
                continue
            input_value = None
            if actual_by_id is not None and rid in actual_by_id.index and stat in actual_by_id:
                input_value = actual_by_id.loc[rid, stat]
            targets.append({"region_id": rid, "variable": spec["variable"],
                            "statistic": stat, "time_range": str(spec["time_range"]),
                            "input_value": input_value, "reference_value": value,
                            "expected_unit": spec.get("unit", "") if stat != "count" else "",
                            "expected_source_table": raster_name(spec),
                            "boundary_tied_centres": ties.get(rid, 0)})
    return targets


def audit_outputs(units, evidence, expected, output_dir, stage, failures):
    """Audit every emitted record; no claim of automatic human semantic review."""
    output_dir = Path(output_dir)
    write_csv(output_dir / "expected_facts.csv", expected)
    ev_map = {ev["evidence_id"]: ev for ev in evidence}
    expectation = {tuple(str(row[k]) for k in KEY): row for row in expected}
    source_bindings = {(k[0], k[1], k[3]): row for k, row in expectation.items()}
    variable_units = {row["variable"]: row["expected_unit"] for row in expected if row["expected_unit"]}
    emitted = {}
    audit, derived = [], []
    missing_periods = {"", "unknown", "none", "nan"}
    for unit in units:
        linked = [ev_map[eid] for eid in unit.get("evidence_ids", []) if eid in ev_map]
        all_links_exist = bool(unit.get("evidence_ids")) and len(linked) == len(unit.get("evidence_ids", []))
        text = str(unit.get("text", ""))
        if unit.get("text_type") != "result":
            kind = next((name for name in ("COMPARE", "INTERPRET", "HETEROG", "CROSSVAR")
                         if f"_{name}_" in unit.get("corpus_id", "")), "other")
            item = {"stage": stage, "corpus_id": unit.get("corpus_id"), "kind": kind,
                    "text": text, "geo_object_id": unit.get("geo_object_id"),
                    "variable": unit.get("variable"), "time_range": unit.get("time_range"),
                    "evidence_ids": json.dumps(unit.get("evidence_ids", [])),
                    "all_links_exist": all_links_exist, "linked_evidence_count": len(linked),
                    "unit_missing": not linked or all(not e.get("unit") for e in linked),
                    "time_missing": str(unit.get("time_range", "")).lower() in missing_periods,
                    "contains_unresolved_template": "${" in text,
                    "contains_nonfinite_numeric_literal": bool(re.search(r"(?<![A-Za-z])(?:nan|[+-]?inf)(?![A-Za-z])", text, re.IGNORECASE)),
                    "claim_type": unit.get("claim_type"),
                    "numeric_check": "not_independently_verifiable_from_linked_evidence"}
            if kind == "COMPARE" and len(linked) == 2 and all(finite(e.get("value")) for e in linked):
                a, b = [float(e["value"]) for e in linked]
                match = re.search(r"差异为(" + NUMBER + r").*?（(" + NUMBER + r")%）", text)
                denominator = max(abs(a), abs(b))
                relation = "高于" if a > b else ("低于" if a < b else "等于")
                item["expected_diff"] = round(abs(a-b), 2)
                item["expected_diff_pct"] = round(item["expected_diff"]/denominator*100, 1) if denominator else None
                item["percentage_check_formula"] = "rounded_absolute_difference/max(abs(a),abs(b))*100"
                item["relation_consistent"] = relation in text
                item["numeric_check"] = bool(match and close(match[1], item["expected_diff"])
                                              and denominator and close(match[2], item["expected_diff_pct"]))
            derived.append(item)
            continue
        ev = linked[0] if linked else {}
        key = (str(unit.get("geo_object_id", "")), str(unit.get("variable", "")),
               str(ev.get("statistic", "")), str(unit.get("time_range", "")))
        target = expectation.get(key)
        source_target = target or source_bindings.get((key[0], key[1], key[3]))
        if target is not None:
            emitted[key] = emitted.get(key, 0) + 1
        match = re.search(r"为\s*(" + NUMBER + ")", text, flags=re.IGNORECASE)
        text_value = float(match[1]) if match else None
        value = ev.get("value")
        numerical = target is not None and (finite(target["input_value"]) or finite(target["reference_value"]))
        error = abs(float(value)-float(target["reference_value"])) if numerical and finite(value) and finite(target["reference_value"]) else None
        expected_unit = "" if key[2] == "count" else variable_units.get(key[1], "")
        raw_unit = str(ev.get("unit", "") or "")
        source_ok = bool(source_target and all_links_exist and str(ev.get("source_id")) == key[0]
                         and str(ev.get("source_table")) == str(source_target["expected_source_table"])
                         and str(ev.get("variable")) == key[1])
        period = str(unit.get("time_range", ""))
        audit.append({
            "stage": stage, "corpus_id": unit.get("corpus_id"), "text": text,
            "region_id": key[0], "variable": key[1], "statistic": key[2], "time_range": period,
            "matched_expected_fact": target is not None, "evidence_id": ev.get("evidence_id"),
            "evidence_source_table": ev.get("source_table"), "evidence_source_id": ev.get("source_id"),
            "all_links_exist": all_links_exist, "source_association_valid": source_ok,
            "input_value": target.get("input_value") if target else None,
            "reference_value": target.get("reference_value") if target else None,
            "evidence_value": value, "text_value": text_value,
            "nonfinite_or_missing_evidence_value": not finite(value),
            "text_evidence_numeric_consistent": close(text_value, value) if numerical else None,
            "input_evidence_numeric_consistent": close(value, target["input_value"]) if numerical else None,
            "reference_abs_error": error,
            "reference_within_tolerance": ((error is not None and error <= (0 if key[2] == "count" else SEMANTICS["absolute_tolerance"] + SEMANTICS["relative_tolerance"] * abs(float(target["reference_value"])))) if target and finite(target["reference_value"]) else None),
            "reference_within_strict_rounding_tolerance": ((error is not None and error <= (0 if key[2] == "count" else SEMANTICS["strict_rounding_diagnostic_tolerance"])) if target and finite(target["reference_value"]) else None),
            "boundary_tied_centres": target.get("boundary_tied_centres") if target else None,
            "expected_unit": expected_unit, "evidence_unit": raw_unit,
            "unit_missing": bool(not raw_unit) if expected_unit else None,
            "unit_correct": canon_unit(raw_unit) == canon_unit(expected_unit) if expected_unit else None,
            "time_missing": period.lower() in missing_periods,
            "evidence_time_consistent": str(ev.get("time_range", "")) == period,
            "text_period_present": period in text if period not in ("static", "unknown", "") else None,
            "contains_unresolved_template": "${" in text,
        })
    coverage = [{**target, "generated_count": emitted.get(key, 0),
                 "covered": emitted.get(key, 0) > 0} for key, target in expectation.items()]
    write_csv(output_dir / "primary_audit.csv", audit)
    write_csv(output_dir / "derived_audit.csv", derived)
    write_csv(output_dir / "coverage.csv", coverage)
    write_csv(output_dir / "all_evidence.csv", evidence)
    primary = pd.DataFrame(audit)
    def fraction(column, data=primary):
        if column not in data:
            return None
        values = data[column].dropna()
        return float(values.astype(bool).mean()) if len(values) else None
    non_tied = primary.loc[primary.boundary_tied_centres.eq(0)] if "boundary_tied_centres" in primary else primary
    error_groups = []
    expected_frame = pd.DataFrame(expected)
    if len(expected_frame):
        for (variable, statistic), expected_group in expected_frame.groupby(["variable", "statistic"], dropna=False):
            group = primary.loc[(primary.variable == variable) & (primary.statistic == statistic)] if len(primary) else pd.DataFrame()
            if "reference_abs_error" not in group:
                group = pd.DataFrame(columns=["reference_abs_error", "boundary_tied_centres"])
            values = group.reference_abs_error.dropna()
            covered_keys = {tuple(str(row[k]) for k in KEY) for row in audit
                            if row["variable"] == variable and row["statistic"] == statistic and row["matched_expected_fact"]}
            passed_keys = {tuple(str(row[k]) for k in KEY) for row in audit
                           if row["variable"] == variable and row["statistic"] == statistic and row["reference_within_tolerance"] is True}
            error_groups.append({
                "stage": stage, "variable": variable, "statistic": statistic,
                "expected_unit": expected_group.expected_unit.iloc[0], "record_count": len(group),
                "expected_fact_count": len(expected_group), "covered_expected_fact_count": len(covered_keys),
                "missing_expected_fact_count": len(expected_group)-len(covered_keys),
                "passed_expected_fact_count": len(passed_keys),
                "end_to_end_tolerance_pass_rate": len(passed_keys)/len(expected_group),
                "finite_error_count": len(values),
                "mean_abs_error": float(values.mean()) if len(values) else None,
                "root_mean_square_error": float(np.sqrt(np.mean(values.to_numpy()**2))) if len(values) else None,
                "max_abs_error": float(values.max()) if len(values) else None,
                "tolerance_pass_rate": fraction("reference_within_tolerance", group),
                "strict_rounding_pass_rate": fraction("reference_within_strict_rounding_tolerance", group),
                "boundary_tied_record_count": int(group.boundary_tied_centres.fillna(0).gt(0).sum()),
            })
    write_csv(output_dir / "numeric_error_groups.csv", error_groups)
    passed_keys = {tuple(str(row[k]) for k in KEY) for row in audit if row["reference_within_tolerance"] is True}
    def valid_numeric(row):
        return (row["matched_expected_fact"] and row["reference_within_tolerance"] is True
                and row["text_evidence_numeric_consistent"] is True
                and row["input_evidence_numeric_consistent"] is True
                and row["source_association_valid"] and row["evidence_time_consistent"]
                and not row["nonfinite_or_missing_evidence_value"])
    valid_primary = sum(valid_numeric(row) for row in audit)
    non_tied_rows = [row for row in audit if not row.get("boundary_tied_centres")]
    tied_rows = [row for row in audit if row.get("boundary_tied_centres")]
    result = {
        "stage": stage, "expected_fact_count": len(expectation), "primary_count": len(audit),
        "derived_count": len(derived), "evidence_count": len(evidence),
        "coverage": len(emitted)/len(expectation) if expectation else None,
        "missing_fact_count": sum(not row["covered"] for row in coverage),
        "duplicate_fact_count": sum(max(count-1, 0) for count in emitted.values()),
        "duplicate_corpus_id_count": len(units)-len({u.get("corpus_id") for u in units}),
        "duplicate_evidence_id_count": len(evidence)-len(ev_map),
        "duplicate_text_count": len(units)-len({u.get("text") for u in units}),
        "unexpected_primary_count": sum(not row["matched_expected_fact"] for row in audit),
        "unexpected_primary_rate": sum(not row["matched_expected_fact"] for row in audit)/len(audit) if audit else None,
        "end_to_end_valid_numeric_primary_count": valid_primary,
        "end_to_end_valid_numeric_primary_rate": valid_primary/len(audit) if audit else None,
        "end_to_end_numeric_definition": "matched reference-eligible fact; finite; reference tolerance pass; source and period binding; table-evidence-text agreement; excludes unit completeness and human semantic review",
        "non_tied_primary_count": len(non_tied_rows), "tied_primary_count": len(tied_rows),
        "non_tied_valid_numeric_primary_count": sum(valid_numeric(row) for row in non_tied_rows),
        "tied_strict_reference_valid_numeric_primary_count": sum(valid_numeric(row) for row in tied_rows),
        "tied_discrepancy_policy": "strict-reference discrepancy on a tied centre is not automatically a software error; compare boundary-inclusive diagnostics",
        "text_evidence_consistency": fraction("text_evidence_numeric_consistent"),
        "input_evidence_consistency": fraction("input_evidence_numeric_consistent"),
        "reference_tolerance_pass_rate": fraction("reference_within_tolerance"),
        "reference_compared_record_count": sum(row["reference_within_tolerance"] is not None for row in audit),
        "reference_passed_expected_fact_count": len(passed_keys),
        "reference_end_to_end_pass_rate": len(passed_keys)/len(expectation) if expectation else None,
        "reference_failed_or_missing_expected_fact_count": len(expectation)-len(passed_keys),
        "nonfinite_or_missing_primary_evidence_count": sum(row["nonfinite_or_missing_evidence_value"] for row in audit),
        "non_tied_reference_tolerance_pass_rate": fraction("reference_within_tolerance", non_tied),
        "strict_rounding_tolerance_pass_rate": fraction("reference_within_strict_rounding_tolerance"),
        "numeric_errors_reported_by": "variable x statistic; see numeric_error_groups.csv; no mixed-unit MAE",
        "source_association_rate": fraction("source_association_valid"),
        "unit_missing_rate": fraction("unit_missing"), "unit_correct_rate_where_known": fraction("unit_correct"),
        "physical_unit_expected_record_count": sum(row["unit_missing"] is not None for row in audit),
        "time_missing_rate": fraction("time_missing"),
        "evidence_time_consistency": fraction("evidence_time_consistent"),
        "derived_with_all_links_rate": fraction("all_links_exist", pd.DataFrame(derived)),
        "derived_numeric_checked_count": sum(isinstance(d["numeric_check"], bool) for d in derived),
        "derived_numeric_unverified_count": sum(not isinstance(d["numeric_check"], bool) for d in derived),
        "derived_relation_mismatch_count": sum(d.get("relation_consistent") is False for d in derived),
        "derived_without_evidence_count": sum(d["linked_evidence_count"] == 0 for d in derived),
        "derived_nonfinite_text_count": sum(d["contains_nonfinite_numeric_literal"] for d in derived),
        "derived_causal_label_count": sum(d.get("claim_type") == "causal" for d in derived),
        "stage_exception_count": sum(f["stage"] == stage for f in failures),
        "human_review_performed": False,
    }
    write_json(output_dir / "metrics.json", result)
    return result


def build_tables(project_dir, prefix, failures, stage):
    settings = GeoCorpusSettings(build_profile="auto", domain="environmental_data", subdomain="experiment")
    project = GeoCorpusProject(root=project_dir, config=settings)
    started = time.perf_counter()
    report = None
    try:
        report = BuildOrchestrator(project).build(spatial_enrich=False, id_prefix=prefix)
    except Exception as error:
        add_failure(failures, stage, error)
    return report, time.perf_counter()-started


def raster_name(spec):
    name = re.sub(r"[^A-Za-z0-9_]+", "_", spec["variable"]).strip("_")
    return name + "_" + re.sub(r"[^A-Za-z0-9_]+", "_", str(spec["time_range"]))


def run_case_b(prepared, rasters, output_dir, n=100, start=0, references=None, failures=None):
    """Original zonal_stats -> time/variable binding -> original auto builder.

    Public benchmark-compatible interface. references may be omitted when only
    running the software; main supplies independent references for full audits.
    """
    failures = failures if failures is not None else []
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    stage = output_dir.name
    frame = prepared_frame(prepared, n, start)
    vector_path = output_dir / "input_boundaries.gpkg"
    frame[["region_id", "geometry"]].to_file(vector_path, driver="GPKG", index=False)
    registry = output_dir / "isolated_registry"
    registry.mkdir(exist_ok=True)
    engine = SpatialQueryEngine(registry)
    project = output_dir / "project"
    stats_dir = project / "statistics"
    stats_dir.mkdir(parents=True, exist_ok=True)
    expected, timing = [], []
    for spec in rasters:
        table = raster_name(spec)
        path = stats_dir / f"{table}.csv"
        started = time.perf_counter()
        actual = None
        try:
            engine.zonal_stats(Path(spec["path"]), vector_path, path,
                               id_field="region_id", stats_list=list(STATS))
            actual = pd.read_csv(path, dtype={"region_id": str})
            # Dataset binding only: no value, unit, or algorithm is changed.
            actual["variable"] = spec["variable"]
            actual["time_range"] = str(spec["time_range"])
            actual.to_csv(path, index=False, encoding="utf-8")
        except Exception as error:
            add_failure(failures, stage, error)
        if references is not None:
            reference, diagnostics = references[spec["variable"]]
            reference = reference.loc[reference.region_id.isin(frame.region_id)]
            expected += raster_expected(reference, actual, spec, diagnostics)
        timing.append({"variable": spec["variable"], "zonal_seconds": time.perf_counter()-started})
    report, build_seconds = build_tables(project, f"GC_{stage.upper()}", failures, stage)
    units, evidence = load_outputs(project)
    write_json(output_dir / "timing.json", {"tables": timing, "build_seconds": build_seconds,
                                           "report": vars(report) if report else None})
    if references is None:
        return {"project": str(project), "build_seconds": build_seconds, "timing": timing}
    return audit_outputs(units, evidence, expected, output_dir, stage, failures)


def rounded_reference(frame):
    result = frame.copy()
    for stat in STATS:
        if stat != "count":
            result[stat] = result[stat].round(4)
    return result


def run_case_a(prepared, output_dir, n, start, failures):
    output_dir.mkdir(parents=True, exist_ok=True)
    stage = output_dir.name
    frame = prepared_frame(prepared, n, start)
    attributes = prepared["attributes"]
    # Only declared source attributes enter this path; sample-order metadata is excluded.
    layer = frame[["region_id", "region_name", *attributes, "geometry"]].copy()
    registry = output_dir / "isolated_registry"
    registry.mkdir()
    layer_id = "real_basins"
    layer.to_parquet(registry / f"{layer_id}.geoparquet", index=False)
    engine = SpatialQueryEngine(registry)
    engine.registry.register(LayerMeta(
        layer_id=layer_id, layer_name=prepared["manifest"]["vector"].get("layer_name", "BasinATLAS "), layer_type="river_basin",
        geometry_type="Polygon", crs=str(layer.crs), id_field="region_id", name_field="region_name",
        fields=[c for c in layer if c != "geometry"], feature_count=len(layer),
        source=prepared["manifest"]["vector"].get("source", ""),
        notes="Experiment-local registry; source values and numeric dtypes unaltered"))
    project = output_dir / "project"
    try:
        engine.layer_to_corpus(layer_id, project, id_prefix=f"GC_{stage.upper()}")
    except Exception as error:
        add_failure(failures, stage, error)
    units, evidence = load_outputs(project)
    expected = expected_long(layer, attributes, period="static", table=f"{layer_id}.geoparquet",
                             unit_map=prepared["manifest"]["vector"].get("units", {}))
    return audit_outputs(units, evidence, expected, output_dir, stage, failures)


def run_case_c(prepared, rasters, references, output_dir, n, start, failures, table_format="mixed"):
    output_dir.mkdir(parents=True, exist_ok=True)
    stage = output_dir.name
    frame = prepared_frame(prepared, n, start)
    project = output_dir / "project"
    stats_dir = project / "statistics"
    stats_dir.mkdir(parents=True)
    expected, formats = [], []
    for index, spec in enumerate(rasters):
        reference, diagnostics = references[spec["variable"]]
        reference = reference.loc[reference.region_id.isin(frame.region_id)].copy()
        table = raster_name(spec)
        rounded = rounded_reference(reference)
        suffix = (".csv" if index % 2 == 0 else ".parquet") if table_format == "mixed" else "." + table_format
        path = stats_dir / (table + suffix)
        if suffix == ".csv":
            rounded.to_csv(path, index=False, encoding="utf-8")
        else:
            rounded.to_parquet(path, index=False)
        expected += raster_expected(reference, rounded, spec, diagnostics)
        formats.append({"variable": spec["variable"], "format": suffix, "path": str(path)})
    report, build_seconds = build_tables(project, f"GC_{stage.upper()}", failures, stage)
    units, evidence = load_outputs(project)
    write_json(output_dir / "timing.json", {"build_seconds": build_seconds, "formats": formats,
                                           "report": vars(report) if report else None})
    return audit_outputs(units, evidence, expected, output_dir, stage, failures)


def compare_formats(csv_dir, parquet_dir, output_dir):
    """Compare identical C inputs represented in two physical table formats."""
    csv_units, csv_evidence = load_outputs(Path(csv_dir) / "project")
    pq_units, pq_evidence = load_outputs(Path(parquet_dir) / "project")
    def normalise(units, evidence):
        ev_map = {e["evidence_id"]: e for e in evidence}
        normalised = []
        for unit in units:
            facts = [{k: e.get(k) for k in ("source_table", "source_id", "variable", "statistic", "value", "unit", "time_range")}
                     for eid in unit.get("evidence_ids", []) if (e := ev_map.get(eid))]
            normalised.append({"group": "primary" if unit.get("text_type") == "result" else "derived",
                               "geo_object_id": unit.get("geo_object_id"), "variable": unit.get("variable"),
                               "time_range": unit.get("time_range"), "text_type": unit.get("text_type"),
                               "text": unit.get("text"), "facts": facts})
        return normalised
    left = normalise(csv_units, csv_evidence)
    right = normalise(pq_units, pq_evidence)
    rows, groups = [], []
    for category in ("primary", "derived"):
        a = [r for r in left if r["group"] == category]
        b = [r for r in right if r["group"] == category]
        key = lambda row: (str(row["geo_object_id"]), str(row["variable"]), str(row["time_range"]),
                           json.dumps([{k: f.get(k) for k in ("statistic", "source_table")} for f in row["facts"]], sort_keys=True))
        a, b = sorted(a, key=key), sorted(b, key=key)
        identical = text_matches = fact_matches = numeric_matches = 0
        for index in range(max(len(a), len(b))):
            ca = a[index] if index < len(a) else None
            cb = b[index] if index < len(b) else None
            matched = ca == cb
            identical += int(matched)
            text_equal = bool(ca is not None and cb is not None and ca["text"] == cb["text"])
            facts_equal = bool(ca is not None and cb is not None and ca["facts"] == cb["facts"])
            numeric_equal = bool(ca is not None and cb is not None and len(ca["facts"]) == len(cb["facts"]))
            if numeric_equal:
                for fa, fb in zip(ca["facts"], cb["facts"]):
                    binding_equal = all(fa.get(k) == fb.get(k) for k in fa if k != "value")
                    value_equal = close(fa.get("value"), fb.get("value")) if finite(fa.get("value")) and finite(fb.get("value")) else fa.get("value") == fb.get("value")
                    numeric_equal &= binding_equal and value_equal
            text_matches += int(text_equal)
            fact_matches += int(facts_equal)
            numeric_matches += int(numeric_equal)
            rows.append({"group": category, "pair_index": index, "exact_match": matched,
                         "text_equal": text_equal, "facts_exact_equal": facts_equal,
                         "numeric_facts_equivalent": numeric_equal,
                         "csv": json.dumps(ca, ensure_ascii=False), "parquet": json.dumps(cb, ensure_ascii=False)})
        groups.append({"group": category, "csv_count": len(a), "parquet_count": len(b),
                       "exact_matching_count": identical,
                       "exact_match_rate": identical/max(len(a), len(b)) if max(len(a), len(b)) else None,
                       "text_exact_match_rate": text_matches/max(len(a), len(b)) if max(len(a), len(b)) else None,
                       "facts_exact_match_rate": fact_matches/max(len(a), len(b)) if max(len(a), len(b)) else None,
                       "numeric_facts_equivalent_rate": numeric_matches/max(len(a), len(b)) if max(len(a), len(b)) else None})
    write_csv(Path(output_dir) / "format_record_comparison.csv", rows)
    write_json(Path(output_dir) / "format_consistency.json", {"groups": groups,
               "ignored_fields": ["corpus_id", "evidence_id", "source"],
               "same_source_table_stems": True, "manual_review_performed": False})
    return groups


def self_test(output_dir):
    """Known-answer checks, explicitly synthetic and separate from real cases."""
    output_dir.mkdir(parents=True, exist_ok=True)
    raster = output_dir / "controlled.tif"
    values = np.arange(1, 17, dtype="float32").reshape(4, 4)
    values[3, 3] = -9999
    with rasterio.open(raster, "w", driver="GTiff", height=4, width=4, count=1,
                       dtype="float32", crs="EPSG:4326", transform=from_origin(0, 4, 1, 1),
                       nodata=-9999) as dst:
        dst.write(values, 1)
    frame = gpd.GeoDataFrame({"region_id": ["R_FULL", "R_TOPLEFT", "R_OUTSIDE", "R_TIE"],
                              "geometry": [box(0, 0, 4, 4), box(0, 2, 2, 4),
                                           box(8, 8, 9, 9), box(0.5, 0.5, 2.5, 2.5)]}, crs=4326)
    ref, diagnostics, metadata = independent_reference(raster, frame, "control", "static")
    indexed = ref.set_index("region_id")
    checks = {
        "full_count_15": indexed.loc["R_FULL", "count"] == 15,
        "full_mean_8": close(indexed.loc["R_FULL", "mean"], 8.),
        "top_left_values_1_2_5_6": close(indexed.loc["R_TOPLEFT", "mean"], 3.5),
        "population_std": close(indexed.loc["R_FULL", "std"], np.std(np.arange(1, 16), ddof=0)),
        "outside_count_zero": indexed.loc["R_OUTSIDE", "count"] == 0,
        "tied_centres_detected": diagnostics.set_index("region_id").loc["R_TIE", "boundary_tied_centres"] > 0,
    }
    # Exercise all three original software paths on known, non-tied inputs too.
    selected = frame.iloc[:2].copy()
    selected["sample_order"] = np.arange(len(selected))
    selected["region_name"] = selected.region_id
    selected["known_value"] = [10., 20.]
    selected.to_file(output_dir / "controlled_objects.gpkg", driver="GPKG", index=False)
    prepared = {
        "prepared_vector": str(output_dir / "controlled_objects.gpkg"), "prepared_layer": "controlled_objects",
        "attributes": ["known_value"],
        "manifest": {"vector": {"source": "synthetic known-answer fixture", "layer_name": "Controlled ",
                                  "units": {"known_value": "m"}}},
    }
    specs, references = [], {}
    for variable in ("control_csv", "control_parquet"):
        specs.append({"path": str(raster), "variable": variable, "unit": "m", "time_range": "static"})
        current = ref.loc[ref.region_id.isin(selected.region_id)].copy()
        current["variable"] = variable
        references[variable] = (current, diagnostics)
    failures = []
    checks_original = [
        run_case_a(prepared, output_dir / "original_A", 2, 0, failures),
        run_case_b(prepared, specs, output_dir / "original_B", 2, 0, references, failures),
        run_case_c(prepared, specs, references, output_dir / "original_C", 2, 0, failures),
    ]
    checks["original_paths_no_exception"] = not failures
    checks["original_paths_full_primary_coverage"] = all(m["coverage"] == 1 for m in checks_original)
    checks["original_paths_text_numeric_consistent"] = all(m["text_evidence_consistency"] == 1 for m in checks_original)
    checks["original_paths_source_association"] = all(m["source_association_rate"] == 1 for m in checks_original)
    write_csv(output_dir / "independent_reference.csv", ref)
    write_csv(output_dir / "selection_diagnostics.csv", diagnostics)
    write_json(output_dir / "self_test.json", {"synthetic": True, "checks": checks,
                                               "passed": all(checks.values()), "raster": metadata,
                                               "original_case_metrics": checks_original, "failures": failures,
                                               "semantics": SEMANTICS})
    if not all(checks.values()):
        raise AssertionError(f"Independent reference self-test failed: {checks}")
    return checks


def summarize_existing(output):
    """Add explicitly denominator-labelled summaries; do not replace run/audit files."""
    output = Path(output).resolve()
    run = json.loads((output / "run_summary.json").read_text(encoding="utf-8"))
    stages = pd.read_csv(output / "metrics_all_cases.csv")
    selections = pd.concat([pd.read_csv(p) for p in (output / "reference").glob("*_selection.csv")],
                           ignore_index=True)
    selection_map = selections.set_index(["region_id", "variable"])
    summaries, error_groups, empty_rows, format_rows = [], [], [], []
    def truth(series):
        return series.astype("string").str.lower().isin(("true", "1", "1.0")).fillna(False)
    for _, stage_info in stages.iterrows():
        stage = stage_info.stage
        primary = pd.read_csv(output / stage / "primary_audit.csv")
        coverage = pd.read_csv(output / stage / "coverage.csv")
        expected_keys = set(map(tuple, coverage[list(KEY)].astype(str).itertuples(index=False, name=None)))
        valid = pd.Series(True, index=primary.index)
        for field in ("matched_expected_fact", "reference_within_tolerance", "text_evidence_numeric_consistent",
                      "input_evidence_numeric_consistent", "source_association_valid", "evidence_time_consistent"):
            valid &= truth(primary[field])
        valid &= ~truth(primary.nonfinite_or_missing_evidence_value)
        valid_keys = set(map(tuple, primary.loc[valid, list(KEY)].astype(str).itertuples(index=False, name=None)))
        physical = primary.expected_unit.notna() & primary.expected_unit.astype(str).str.len().gt(0)
        nonempty_units = primary.evidence_unit.notna() & primary.evidence_unit.astype(str).str.strip().str.len().gt(0)
        try:
            derived = pd.read_csv(output / stage / "derived_audit.csv")
        except pd.errors.EmptyDataError:
            derived = pd.DataFrame()
        derived_recheck = []
        if len(derived):
            source_units, source_evidence = load_outputs(output / stage / "project")
            ev_map = {ev["evidence_id"]: ev for ev in source_evidence}
            for unit in source_units:
                if "_COMPARE_" not in unit.get("corpus_id", ""):
                    continue
                linked = [ev_map[eid] for eid in unit.get("evidence_ids", []) if eid in ev_map]
                if len(linked) != 2 or not all(finite(ev.get("value")) for ev in linked):
                    continue
                a, b = [float(ev["value"]) for ev in linked]
                denominator = max(abs(a), abs(b))
                if denominator == 0:
                    continue
                difference = round(abs(a-b), 2)
                rounded_pct = round(difference/denominator*100, 1)
                unrounded_pct = round(abs(a-b)/denominator*100, 1)
                match = re.search(r"差异为(" + NUMBER + r").*?（(" + NUMBER + r")%）", unit["text"])
                derived_recheck.append({"corpus_id": unit["corpus_id"], "value_a": a, "value_b": b,
                                        "difference_rounded_2dp": difference,
                                        "percentage_rounded_difference": rounded_pct,
                                        "percentage_unrounded_difference": unrounded_pct,
                                        "implementation_order_numeric_pass": bool(match and close(match[1], difference) and close(match[2], rounded_pct)),
                                        "unrounded_numerator_numeric_pass": bool(match and close(match[1], difference) and close(match[2], unrounded_pct)),
                                        "text": unit["text"]})
        write_csv(output / stage / "derived_numeric_recheck_v2.csv", derived_recheck)
        item = {
            "stage": stage,
            "reference_eligible_unique_facts": len(expected_keys),
            "unique_valid_retained_reference_facts": len(valid_keys & expected_keys),
            "unique_fact_retention_rate": len(valid_keys & expected_keys)/len(expected_keys) if expected_keys else None,
            "emitted_primary_records": len(primary), "valid_emitted_numeric_primary_records": int(valid.sum()),
            "emitted_numeric_acceptance_rate": float(valid.mean()) if len(primary) else None,
            "unmatched_emitted_primary_records": int((~truth(primary.matched_expected_fact)).sum()),
            "nonfinite_primary_records": int(truth(primary.nonfinite_or_missing_evidence_value).sum()),
            "missing_expected_unique_facts": int((~truth(coverage.covered)).sum()),
            "source_association_numerator": int(truth(primary.source_association_valid).sum()),
            "source_association_denominator": len(primary),
            "physical_unit_present_numerator": int((physical & ~truth(primary.unit_missing)).sum()),
            "physical_unit_expected_denominator": int(physical.sum()),
            "actual_nonempty_unit_record_count": int(nonempty_units.sum()),
            "all_primary_unit_record_denominator": len(primary),
            "count_excluded_from_physical_unit_denominator": True,
            "temporal_metadata_missing_records": int(truth(primary.time_missing).sum()),
            "tied_primary_records": int(primary.boundary_tied_centres.fillna(0).gt(0).sum()),
            "human_review_performed": False,
            "coverage_numerator": int(truth(coverage.covered).sum()), "coverage_denominator": len(coverage),
            "duplicate_fact_count": int(stage_info.duplicate_fact_count),
            "duplicate_text_count": int(stage_info.duplicate_text_count),
            "derived_record_count": len(derived),
            "derived_with_existing_evidence_count": int(truth(derived.all_links_exist).sum()) if len(derived) else 0,
            "derived_without_evidence_count": int((pd.to_numeric(derived.linked_evidence_count) == 0).sum()) if len(derived) else 0,
            "derived_numeric_verifiable_count": len(derived_recheck),
            "derived_numeric_verified_pass_count": sum(row["implementation_order_numeric_pass"] for row in derived_recheck),
            "derived_original_audit_numeric_pass_count": int(truth(derived.numeric_check).sum()) if len(derived) else 0,
            "derived_unrounded_numerator_pass_count": sum(row["unrounded_numerator_numeric_pass"] for row in derived_recheck),
            "derived_verification_formula": "difference=round(abs(a-b),2); percentage=round(difference/max(abs(a),abs(b))*100,1)",
            "derived_nonfinite_text_count": int(truth(derived.contains_nonfinite_numeric_literal).sum()) if len(derived) else 0,
            "derived_causal_label_count": int(derived.claim_type.eq("causal").sum()) if len(derived) else 0,
        }
        if not stage.startswith("real_A_"):
            pairs = primary[["region_id", "variable"]].drop_duplicates()
            empty_pairs = []
            for _, pair in pairs.iterrows():
                diagnostic = selection_map.loc[(pair.region_id, pair.variable)]
                if int(diagnostic.valid_cell_count) != 0:
                    continue
                group = primary.loc[(primary.region_id == pair.region_id) & (primary.variable == pair.variable)]
                count = group.loc[group.statistic == "count"]
                count_value = count.evidence_value.iloc[0] if len(count) else None
                reason = ("outside_raster_extent" if diagnostic.window_cell_count == 0 else
                          ("no_pixel_centre_inside" if diagnostic.strict_inside_centres == 0 else "all_selected_centres_nodata"))
                empty_rows.append({"stage": stage, "region_id": pair.region_id, "variable": pair.variable,
                                   "empty_reason": reason, "reference_count": 0, "software_count": count_value,
                                   "software_count_zero": close(count_value, 0),
                                   "emitted_records": len(group),
                                   "nonfinite_continuous_records": int(truth(group.loc[group.statistic != "count", "nonfinite_or_missing_evidence_value"]).sum()),
                                   "boundary_tied_centres": int(diagnostic.boundary_tied_centres)})
                empty_pairs.append((pair.region_id, pair.variable))
            empty_set = set(empty_pairs)
            nonempty = ~pd.Series([(row.region_id, row.variable) in empty_set for _, row in primary.iterrows()], index=primary.index)
            continuous = primary.statistic != "count"
            eligible = nonempty & continuous
            pass_mask = truth(primary.reference_within_tolerance)
            item.update({"object_variable_pairs": len(pairs), "empty_object_variable_pairs": len(empty_pairs),
                         "nonempty_continuous_records": int(eligible.sum()),
                         "nonempty_continuous_tolerance_pass_count": int((eligible & pass_mask).sum()),
                         "nonempty_continuous_tolerance_pass_rate": float(pass_mask.loc[eligible].mean()) if eligible.any() else None,
                         "nonempty_count_records": int((nonempty & ~continuous).sum()),
                         "nonempty_count_exact_pass_count": int((nonempty & ~continuous & pass_mask).sum()),
                         "empty_zone_representation_is_separate_from_continuous_statistic_accuracy": True})
            for (variable, statistic), group in primary.loc[nonempty].groupby(["variable", "statistic"]):
                errors = pd.to_numeric(group.reference_abs_error, errors="coerce").dropna()
                error_groups.append({"stage": stage, "variable": variable, "statistic": statistic,
                                     "unit": group.expected_unit.iloc[0], "nonempty_record_count": len(group),
                                     "finite_error_count": len(errors),
                                     "tolerance_pass_count": int(truth(group.reference_within_tolerance).sum()),
                                     "mean_absolute_error": float(errors.mean()) if len(errors) else None,
                                     "maximum_absolute_error": float(errors.max()) if len(errors) else None,
                                     "root_mean_square_error": float(np.sqrt(np.mean(errors.to_numpy()**2))) if len(errors) else None})
        summaries.append(item)
    for cohort in ("base", "reuse"):
        path = output / f"real_C_formats_{cohort}" / "format_record_comparison.csv"
        if not path.exists():
            continue
        comparison = pd.read_csv(path)
        for category, group in comparison.groupby("group"):
            format_rows.append({"cohort": cohort, "group": category, "paired_record_count": len(group),
                                **{f"{field}_numerator": int(truth(group[field]).sum())
                                   for field in ("exact_match", "text_equal", "facts_exact_equal", "numeric_facts_equivalent")}})
    write_csv(output / "evaluation_summary_v2.csv", summaries)
    write_csv(output / "nonempty_numeric_errors_v2.csv", error_groups)
    write_csv(output / "empty_zone_representation_v2.csv", empty_rows)
    write_csv(output / "format_consistency_counts_v2.csv", format_rows)
    write_json(output / "evaluation_summary_v2.json", {
        "summary_scope": "supplementary denominator/empty-zone stratification; original outputs and original audits unchanged",
        "original_runner_sha256": run.get("runner_sha256"), "summary_runner_sha256": file_hash(__file__),
        "observed_output_rate_name": "emitted_numeric_acceptance_rate, not an end-to-end completeness rate",
        "end_to_end_name": "unique_fact_retention_rate = unique valid retained reference facts / reference-eligible unique facts",
        "unit_completeness_is_separate": True, "human_review_performed": False,
        "derived_recheck_note": "Original audits are unchanged. v2 reports implementation's rounded-difference percentage order and the unrounded-numerator alternative separately; differences between these conventions are not labelled algorithm errors.",
        "cases": summaries, "format_consistency_counts": format_rows,
        "unique_empty_input_object_variable_pairs": int(selections.loc[selections.valid_cell_count.eq(0), ["region_id", "variable"]].drop_duplicates().shape[0]),
        "empty_zone_case_pair_record_count": len(empty_rows),
        "nonempty_error_group_count": len(error_groups),
        "nonempty_numeric_errors": error_groups, "empty_zone_representation": empty_rows,
    })
    return summaries


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--summarize-existing", type=Path)
    parser.add_argument("--seed", type=int, default=2026)
    parser.add_argument("--n-base", type=int, default=100)
    parser.add_argument("--n-reuse", type=int, default=100)
    parser.add_argument("--sample-sizes", default="100,500,1000")
    parser.add_argument("--self-test-only", action="store_true")
    parser.add_argument("--skip-self-test", action="store_true")
    args = parser.parse_args(argv)
    if args.summarize_existing:
        summarize_existing(args.summarize_existing)
        return 0
    if args.output is None:
        parser.error("--output is required for a new run")
    output = args.output.resolve()
    if output.exists() and any(output.iterdir()):
        parser.error("Output must be a new or empty directory; no existing experiment is overwritten")
    output.mkdir(parents=True, exist_ok=True)
    failures, metrics = [], []
    started = time.perf_counter()
    with (output / "execution.log").open("w", encoding="utf-8") as log:
        with contextlib.redirect_stdout(log), contextlib.redirect_stderr(log):
            try:
                if not args.skip_self_test:
                    self_test(output / "self_test")
                if args.self_test_only:
                    write_json(output / "run_summary.json", {"synthetic_only": True, "self_test_passed": True})
                    return 0
                if args.manifest is None:
                    raise ValueError("--manifest is required unless --self-test-only is used")
                manifest = load_manifest(args.manifest)
                prepared = prepare_samples(manifest, output / "prepared", args.seed,
                                           args.n_base, args.n_reuse,
                                           tuple(int(s) for s in args.sample_sizes.split(",")))
                print(f"PREPARED_MANIFEST={output / 'prepared' / 'prepared_manifest.json'}", flush=True)
                frame = prepared_frame(prepared, args.n_base + args.n_reuse)
                rasters = manifest["rasters"]
                references, raster_metadata = {}, []
                for spec in rasters:
                    ref, diagnostics, meta = independent_reference(spec["path"], frame,
                                                                    spec["variable"], spec["time_range"])
                    references[spec["variable"]] = (ref, diagnostics)
                    raster_metadata.append({**spec, **meta})
                    write_csv(output / "reference" / f"{raster_name(spec)}.csv", ref)
                    write_csv(output / "reference" / f"{raster_name(spec)}_selection.csv", diagnostics)
                write_json(output / "raster_metadata.json", raster_metadata)
                for cohort, start, n in (("base", 0, args.n_base), ("reuse", args.n_base, args.n_reuse)):
                    for label, function in (
                        ("A", lambda out: run_case_a(prepared, out, n, start, failures)),
                        ("B", lambda out: run_case_b(prepared, rasters, out, n, start, references, failures)),
                        ("C_csv", lambda out: run_case_c(prepared, rasters, references, out, n, start, failures, "csv")),
                        ("C_parquet", lambda out: run_case_c(prepared, rasters, references, out, n, start, failures, "parquet")),
                    ):
                        stage = f"real_{label}_{cohort}"
                        try:
                            metrics.append(function(output / stage))
                        except Exception as error:
                            add_failure(failures, stage, error)
                    compare_formats(output / f"real_C_csv_{cohort}", output / f"real_C_parquet_{cohort}",
                                    output / f"real_C_formats_{cohort}")
                versions = {}
                for name in ("numpy", "pandas", "geopandas", "shapely", "rasterio", "pyarrow"):
                    versions[name] = importlib.metadata.version(name)
                write_json(output / "run_summary.json", {
                    "manifest": manifest, "seed": args.seed, "n_base": args.n_base,
                    "n_reuse": args.n_reuse, "metrics": metrics, "semantics": SEMANTICS,
                    "failures": failures, "elapsed_seconds": time.perf_counter()-started,
                    "python": sys.version, "platform": platform.platform(), "versions": versions,
                    "runner_sha256": file_hash(__file__),
                    "software_source_sha256": {name: file_hash(WORKSPACE / "geocorpus-builder" / "src" / "geocorpus_builder" / name)
                                               for name in ("builder/engine.py", "builder/templates.py", "builder/evidence_factory.py", "spatial/engine.py")},
                    "software_modified": False, "human_review_performed": False,
                })
                write_csv(output / "metrics_all_cases.csv", metrics)
                summarize_existing(output)
            except Exception as error:
                add_failure(failures, "setup_or_reference", error)
            finally:
                write_json(output / "failures.json", failures)
    print(json.dumps({"output": str(output), "case_count": len(metrics),
                      "failure_count": len(failures), "elapsed_seconds": time.perf_counter()-started}))
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
