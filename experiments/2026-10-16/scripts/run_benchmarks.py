"""Measure the original raster-to-corpus workflow in isolated worker processes."""

from __future__ import annotations

import argparse
import contextlib
import json
import os
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import psutil


ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "geocorpus-builder" / "src"))
STATS = ["mean", "median", "std", "min", "max", "count"]


def load_rasters(manifest_path: Path) -> list[dict]:
    data = json.loads(manifest_path.read_text(encoding="utf-8"))
    records = []
    for item in data["rasters"]:
        item = dict(item)
        path = Path(item["path"])
        item["path"] = str(path if path.is_absolute() else (manifest_path.parent / path).resolve())
        records.append(item)
    return records


def worker(args: argparse.Namespace) -> None:
    import geopandas as gpd
    from geocorpus_builder.builder.engine import BuildOrchestrator
    from geocorpus_builder.config.project import GeoCorpusProject
    from geocorpus_builder.spatial import SpatialQueryEngine

    target = args.output.resolve()
    target.mkdir(parents=True, exist_ok=False)
    vector = gpd.read_file(args.vector)
    if "sample_order" in vector.columns:
        vector = vector.sort_values("sample_order")
    if len(vector) < args.n:
        raise ValueError(f"Only {len(vector)} objects available for n={args.n}")
    vector = vector.iloc[:args.n].copy()
    boundary = target / "boundary.gpkg"
    vector.to_file(boundary, driver="GPKG", index=False)
    selected = load_rasters(args.manifest)[:args.m]
    if len(selected) != args.m:
        raise ValueError("Insufficient raster files")
    project = GeoCorpusProject.init(target / "project")
    project.config.build_profile = "auto"
    project.config.domain = "environment"
    project.config.subdomain = "benchmark"
    stats_dir = project.root / "statistics"
    before_rss = psutil.Process().memory_info().rss
    with (target / "workflow.log").open("w", encoding="utf-8") as log, contextlib.redirect_stdout(log), contextlib.redirect_stderr(log):
        engine = SpatialQueryEngine()
        start = time.perf_counter()
        for i, raster in enumerate(selected):
            name = f"v{i:02d}_{Path(raster['path']).stem}"
            engine.zonal_stats(Path(raster["path"]), boundary, stats_dir / f"{name}.csv", id_field="region_id", stats_list=STATS)
        after_stats = time.perf_counter()
        report = BuildOrchestrator(project).build(spatial_enrich=False, id_prefix="GC_BENCH")
        end = time.perf_counter()
    corpus_path = project.root / "corpus" / "corpus_units.jsonl"
    evidence_path = project.root / "evidence" / "evidence_links.jsonl"
    with corpus_path.open(encoding="utf-8") as handle:
        units = [json.loads(line) for line in handle if line.strip()]
    base = sum(unit.get("text_type") == "result" for unit in units)
    result = {
        "n_objects": args.n, "n_rasters": args.m, "n_statistics": len(STATS),
        "statistics_seconds": after_stats - start,
        "build_seconds": end - after_stats,
        "workflow_seconds": end - start,
        "units_created": report.units_created, "base_result_units": base,
        "derived_units": len(units) - base, "evidence_created": report.evidence_created,
        "throughput_all_units_per_second": report.units_created / (end - start),
        "throughput_base_units_per_second": base / (end - start),
        "baseline_rss_bytes": before_rss,
        "output_bytes": corpus_path.stat().st_size + evidence_path.stat().st_size,
        "errors": report.errors, "warnings": report.warnings,
        "workflow_completed": not report.errors and bool(units),
        "timed_scope": "read prepared boundary and rasters, zonal statistics, CSV write/read, original builder, corpus/evidence writes",
        "setup_excluded": "sample selection, subset boundary preparation, project initialization, data downloads, reference computation",
    }
    (target / "worker_result.json").write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")


def parent(args: argparse.Namespace) -> None:
    import pandas as pd

    args.output.mkdir(parents=True, exist_ok=True)
    summary = []
    environment = os.environ.copy()
    environment.update({"OMP_NUM_THREADS": "1", "OPENBLAS_NUM_THREADS": "1", "MKL_NUM_THREADS": "1", "NUMEXPR_NUM_THREADS": "1", "PYTHONHASHSEED": "2026", "PYTHONIOENCODING": "utf-8"})
    for n in map(int, args.sizes.split(",")):
        for m in map(int, args.raster_counts.split(",")):
            for repeat in range(args.repeats):
                directory = args.output / f"n{n}_m{m}_r{repeat}"
                if (directory / "measurement.json").exists():
                    summary.append(json.loads((directory / "measurement.json").read_text(encoding="utf-8")))
                    continue
                command = [sys.executable, str(Path(__file__).resolve()), "--worker", "--vector", str(args.vector.resolve()), "--manifest", str(args.manifest.resolve()), "--output", str(directory.resolve()), "--n", str(n), "--m", str(m)]
                stdout_path = args.output / f"n{n}_m{m}_r{repeat}.stdout.log"
                started = time.perf_counter()
                peak = 0
                timed_out = False
                with stdout_path.open("w", encoding="utf-8") as log:
                    process = subprocess.Popen(command, stdout=log, stderr=subprocess.STDOUT, env=environment, cwd=ROOT)
                    monitored = psutil.Process(process.pid)
                    while process.poll() is None:
                        try:
                            rss = monitored.memory_info().rss + sum(child.memory_info().rss for child in monitored.children(recursive=True) if child.is_running())
                            peak = max(peak, rss)
                        except (psutil.NoSuchProcess, psutil.AccessDenied):
                            pass
                        if time.perf_counter() - started > args.timeout:
                            for child in monitored.children(recursive=True):
                                child.kill()
                            process.kill()
                            timed_out = True
                            break
                        time.sleep(0.05)
                    exit_code = process.wait()
                row = {
                    "n_objects": n, "n_rasters": m, "repeat": repeat,
                    "run_label": "first_observed" if repeat == 0 else "subsequent",
                    "cache_state": "OS file cache not flushed or controlled",
                    "exit_code": exit_code, "timeout": timed_out,
                    "process_wall_seconds": time.perf_counter() - started,
                    "peak_rss_bytes": peak,
                    "rss_sampling_seconds": 0.05,
                    "utc": datetime.now(timezone.utc).isoformat(),
                }
                if (directory / "worker_result.json").exists():
                    row.update(json.loads((directory / "worker_result.json").read_text(encoding="utf-8")))
                directory.mkdir(parents=True, exist_ok=True)
                (directory / "measurement.json").write_text(json.dumps(row, ensure_ascii=False, indent=2), encoding="utf-8")
                summary.append(row)
                (args.output / "all_measurements.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
                print(json.dumps({key: row.get(key) for key in ["n_objects", "n_rasters", "repeat", "exit_code", "workflow_seconds", "peak_rss_bytes"]}), flush=True)
    frame = pd.DataFrame(summary)
    frame.to_csv(args.output / "all_measurements.csv", index=False, encoding="utf-8-sig")
    if "workflow_completed" not in frame:
        frame["workflow_completed"] = False
    good = frame.loc[(frame["exit_code"] == 0) & frame["workflow_completed"].fillna(False) & (frame["repeat"] > 0)]
    if not good.empty:
        columns = ["statistics_seconds", "build_seconds", "workflow_seconds", "base_result_units", "units_created", "throughput_base_units_per_second", "throughput_all_units_per_second", "peak_rss_bytes", "output_bytes"]
        table = good.groupby(["n_objects", "n_rasters"])[columns].median().reset_index()
        table.to_csv(args.output / "subsequent_medians.csv", index=False, encoding="utf-8-sig")
        print(table.to_string(index=False), flush=True)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--vector", type=Path, required=True)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--sizes", default="100,500,1000")
    parser.add_argument("--raster-counts", default="1,3,5")
    parser.add_argument("--repeats", type=int, default=4)
    parser.add_argument("--timeout", type=float, default=900)
    parser.add_argument("--worker", action="store_true")
    parser.add_argument("--n", type=int)
    parser.add_argument("--m", type=int)
    args = parser.parse_args()
    worker(args) if args.worker else parent(args)


if __name__ == "__main__":
    main()
