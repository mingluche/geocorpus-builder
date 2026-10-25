"""Audit completed experiment artifacts without rerunning the tested software."""

from __future__ import annotations

import hashlib
import json
import statistics
from datetime import datetime, timezone
from pathlib import Path


def read_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def main() -> None:
    experiment = Path(__file__).resolve().parents[1]
    results = experiment / "results"
    before = read_json(results / "environment_before.json")
    after = read_json(results / "environment_after.json")
    source_names = set(before["source_sha256"]) | set(after["source_sha256"])
    changed = sorted(
        name for name in source_names
        if before["source_sha256"].get(name) != after["source_sha256"].get(name)
    )
    assert not changed, changed
    assert before["git_status"] == after["git_status"]

    real = results / "real_protocol_main"
    real_summary = read_json(real / "evaluation_summary_v2.json")
    execution = read_json(real / "run_summary.json")
    snapshot_hash = hashlib.sha256((real / "runner_snapshot.py").read_bytes()).hexdigest()
    assert snapshot_hash == execution["runner_sha256"]
    assert not execution["failures"]

    runs = read_json(results / "benchmarks_protocol" / "all_measurements.json")
    failed_runs = [
        run for run in runs
        if run["exit_code"] != 0 or not run["workflow_completed"] or run["errors"]
    ]
    assert len(runs) == 36
    assert not failed_runs
    assert all(
        run["base_result_units"] == run["n_objects"] * run["n_rasters"] * 6
        for run in runs
    )
    medians = []
    for n in (100, 500, 1000):
        for m in (1, 3, 5):
            group = [
                run for run in runs
                if run["n_objects"] == n and run["n_rasters"] == m and run["repeat"] > 0
            ]
            assert len(group) == 3
            medians.append({
                "objects": n,
                "rasters": m,
                "subsequent_repetitions": len(group),
                "statistics_seconds": statistics.median(run["statistics_seconds"] for run in group),
                "build_seconds": statistics.median(run["build_seconds"] for run in group),
                "workflow_seconds": statistics.median(run["workflow_seconds"] for run in group),
                "basic_records": group[0]["base_result_units"],
                "derived_records": group[0]["derived_units"],
                "total_records": group[0]["units_created"],
                "peak_process_rss_mib": statistics.median(run["peak_rss_bytes"] for run in group) / 2**20,
                "output_bytes": group[0]["output_bytes"],
            })

    controlled = read_json(
        results / "controlled_20261016T100106326636Z" / "controlled_protocol_summary.json"
    )
    summary = {
        "finalized_at_utc": datetime.now(timezone.utc).isoformat(),
        "experiment_kind": "executed real-data workflows, synthetic controls and process benchmarks",
        "source_files_verified_unchanged": len(source_names),
        "source_files_changed": changed,
        "git_status_unchanged": before["git_status"] == after["git_status"],
        "execution_runner_snapshot_hash_matches": True,
        "real_project_count": len(real_summary["cases"]),
        "real_cases": real_summary["cases"],
        "format_consistency_counts": real_summary["format_consistency_counts"],
        "unique_empty_input_object_variable_pairs": real_summary["unique_empty_input_object_variable_pairs"],
        "benchmark_run_count": len(runs),
        "benchmark_failed_or_reported_error_count": len(failed_runs),
        "benchmark_basic_record_cardinality_all_match": True,
        "benchmark_medians": medians,
        "benchmark_cache_policy": "OS file cache not flushed or controlled; medians use three subsequent runs",
        "benchmark_throughput_scope": "emitted records, not independently validated environmental facts",
        "controlled_main_statistics": controlled["main_six_statistics"],
        "controlled_finite_reference": controlled["main_six_finite_reference"],
        "controlled_empty_reference": controlled["main_six_empty_reference"],
        "not_measured": [
            "human semantic review",
            "human configuration time or labor savings",
            "language-model training or transfer performance",
        ],
        "formal_real_result_directory": str(real),
        "pilot_outputs_excluded": ["real_main", "real_protocol_check", "real_reference_self_test", "real_runner_self_test"],
        "environment": {
            key: after[key] for key in (
                "python", "executable", "platform", "cpu_name", "logical_cpus",
                "physical_cpus", "total_ram_bytes", "packages",
            )
        },
    }
    output = results / "experiment_results_summary.json"
    output.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({
        "output": str(output),
        "unchanged_source_files": len(source_names),
        "formal_projects": len(real_summary["cases"]),
        "benchmark_runs": len(runs),
        "benchmark_failures": len(failed_runs),
    }, ensure_ascii=False))


if __name__ == "__main__":
    main()
