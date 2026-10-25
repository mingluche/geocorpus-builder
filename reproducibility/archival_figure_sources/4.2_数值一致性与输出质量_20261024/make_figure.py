"""Redraw Section 4.2 from stored audits; do not rerun or modify the software."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from matplotlib.lines import Line2D
from PIL import Image


ROOT = Path(__file__).resolve().parents[2]
OUT = Path(__file__).resolve().parent
REAL = ROOT / "experiments/2026-10-16/results/real_protocol_main"
CONTROL = ROOT / "experiments/2026-10-16/results/controlled_20261016T100106326636Z"
VARIABLES = ["elevation", "prec_01", "prec_07", "tavg_01", "tavg_07"]
STATISTICS = ["mean", "median", "std", "min", "max"]


def flags(series: pd.Series) -> pd.Series:
    return series.astype(str).str.lower().eq("true")


def main() -> None:
    data_dir = OUT / "plot_data"
    data_dir.mkdir(parents=True, exist_ok=True)
    inputs = [REAL / f"real_B_{cohort}/primary_audit.csv" for cohort in ("base", "reuse")]
    inputs += [CONTROL / "controlled_protocol_comparison.csv", REAL / "evaluation_summary_v2.csv"]
    frames = []
    for cohort, path in zip(("base", "reuse"), inputs[:2]):
        frame = pd.read_csv(path, float_precision="round_trip")
        frame["cohort"] = cohort
        frames.append(frame)
    full = pd.concat(frames, ignore_index=True)
    finite = full[
        full.statistic.isin(STATISTICS)
        & np.isfinite(full.reference_value)
        & np.isfinite(full.evidence_value)
    ].copy()
    assert len(finite) == 4950
    finite["absolute_error"] = np.abs(finite.evidence_value - finite.reference_value)
    finite["tolerance"] = 5e-5 + 1e-6 * np.abs(finite.reference_value)
    finite["normalized_error"] = finite.absolute_error / finite.tolerance
    assert (finite.normalized_error <= 1).all()
    maxima = finite.groupby(["variable", "statistic"], sort=False).agg(
        n=("normalized_error", "size"),
        maximum_normalized_error=("normalized_error", "max"),
    ).reset_index()
    assert len(maxima) == 25 and (maxima.n == 198).all()
    counts = full[(full.statistic == "count") & (full.reference_value > 0)].copy()
    assert len(counts) == 990
    assert (counts.reference_value == counts.evidence_value).all()

    controlled = pd.read_csv(inputs[2], float_precision="round_trip")
    controlled = controlled[controlled.statistic.isin(STATISTICS + ["count"])].copy()
    controlled["passed"] = flags(controlled.chapter3_protocol_pass)
    declared = {
        "nan_declared_nodata", "sentinel_declared_nodata",
        "sentinel_explicit_override", "signed_nan_sentinel",
    }
    undeclared = {
        "positive_no_nodata", "nan_no_nodata", "all_zero_no_nodata", "signed_zero_no_nodata",
    }
    controlled["condition"] = controlled.variant.map(
        {**{key: "NoData declared or specified" for key in declared},
         **{key: "NoData not declared" for key in undeclared},
         "float32_precision": "float32 precision control"}
    )
    assert controlled.condition.notna().all()
    conditions = ["NoData declared or specified", "float32 precision control", "NoData not declared"]
    summary = controlled.groupby("condition").agg(
        passed=("passed", "sum"), checks=("passed", "size")
    ).reindex(conditions).reset_index()
    summary["percentage"] = 100 * summary.passed / summary.checks
    assert list(summary.passed) == [192, 46, 121]
    assert list(summary.checks) == [192, 48, 192]
    assert len(controlled) == 432 and controlled.passed.sum() == 359

    finite[["cohort", "region_id", "variable", "statistic", "reference_value", "evidence_value",
            "absolute_error", "tolerance", "normalized_error"]].to_csv(
                data_dir / "real_continuous_comparisons.csv", index=False, encoding="utf-8-sig")
    maxima.to_csv(data_dir / "maximum_normalized_errors.csv", index=False, encoding="utf-8-sig")
    summary.to_csv(data_dir / "controlled_condition_summary.csv", index=False, encoding="utf-8-sig")

    plt.rcParams.update({
        "font.family": "Arial", "font.size": 8,
        "axes.labelsize": 8, "axes.linewidth": 0.6,
        "xtick.labelsize": 7.5, "ytick.labelsize": 7.7,
        "xtick.major.size": 3, "ytick.major.size": 0,
        "xtick.major.width": 0.6, "ytick.major.width": 0.6,
        "text.color": "#202020", "axes.labelcolor": "#202020",
        "xtick.color": "#303030", "ytick.color": "#303030",
        "svg.fonttype": "none", "savefig.facecolor": "white",
    })
    fig = plt.figure(figsize=(180 / 25.4, 92 / 25.4), facecolor="white")
    left = fig.add_axes([0.166, 0.18, 0.374, 0.56])
    right = fig.add_axes([0.79, 0.18, 0.17, 0.56])
    styles = {
        "mean": ("Mean", "o", "#356887"),
        "median": ("Median", "s", "#4C8270"),
        "std": ("SD", "D", "#AB7839"),
        "min": ("Min", "v", "#686868"),
        "max": ("Max", "^", "#985F72"),
    }
    offsets = np.linspace(0.24, -0.24, 5)
    for j, variable in enumerate(VARIABLES):
        row = maxima[maxima.variable == variable].set_index("statistic")
        y = 4 - j
        for k, statistic in enumerate(STATISTICS):
            label, marker, color = styles[statistic]
            value = row.loc[statistic, "maximum_normalized_error"]
            left.plot(value, y + offsets[k], marker=marker, color=color,
                      markersize=4, markeredgewidth=0.5, linestyle="none", zorder=3)
    for y in (0.5, 1.5, 2.5, 3.5):
        left.axhline(y, color="#EBEBEB", linewidth=0.45, zorder=0)
    left.axvline(1, color="#606060", linewidth=0.75, linestyle=(0, (4, 3)), zorder=1)
    left.set_xlim(-0.045, 1.065)
    left.set_ylim(-0.45, 4.45)
    left.set_xticks([0, 0.25, 0.5, 0.75, 1], ["0", "0.25", "0.50", "0.75", "1.00"])
    left.set_yticks(range(5), ["Jul. temperature", "Jan. temperature", "Jul. precipitation",
                              "Jan. precipitation", "Elevation"])
    left.tick_params(axis="y", pad=7)
    left.set_xlabel("Maximum normalized error", labelpad=7)
    handles = [Line2D([], [], linestyle="none", marker=marker, color=color,
                      markersize=4, label=label) for label, marker, color in styles.values()]
    fig.legend(handles=handles, loc="upper left", bbox_to_anchor=(0.155, 0.888),
               ncol=3, frameon=False, fontsize=7.5, handlelength=1,
               handletextpad=0.35, columnspacing=1.0, borderaxespad=0,
               labelspacing=0.5)

    y_positions = np.array([2, 1, 0])
    for y, (_, row) in zip(y_positions, summary.iterrows()):
        right.hlines(y, 0, row.percentage, color="#B9B9B9", linewidth=0.7, zorder=1)
        right.plot(row.percentage, y, "o", color="#356887", markersize=4.5, zorder=2)
        percent = f"{row.percentage:.1f}".removesuffix(".0")
        right.annotate(f"{int(row.passed)}/{int(row.checks)} ({percent}%)",
                       (row.percentage, y), xytext=(-1, 10), textcoords="offset points",
                       ha="right", va="bottom", fontsize=7.5, color="#202020")
    right.set_yticks([2, 1, 0], ["NoData declared\nor specified", "float32 precision\ncontrol",
                                "NoData not\ndeclared"])
    right.tick_params(axis="y", pad=9)
    right.set_ylim(-0.45, 2.55)
    right.set_xlim(-2, 109)
    right.set_xticks([0, 50, 100])
    right.set_xlabel("Checks passed (%)", labelpad=7)
    for ax in (left, right):
        ax.spines[["top", "right"]].set_visible(False)
        ax.spines["left"].set_color("#606060")
        ax.spines["bottom"].set_color("#606060")
    fig.text(0.035, 0.95, "(a) Real-data agreement", fontsize=9, weight="bold", va="top")
    fig.text(0.605, 0.95, "(b) Controlled tests", fontsize=9, weight="bold", va="top")
    fig.text(0.605, 0.86, "Synthetic scenarios", fontsize=7.6, color="#606060", va="top")

    fig.canvas.draw()
    renderer = fig.canvas.get_renderer()
    bounds = fig.bbox
    outside = []
    from matplotlib.text import Text
    for artist in fig.findobj(Text):
        if not artist.get_visible() or not artist.get_text():
            continue
        box = artist.get_window_extent(renderer)
        if box.x0 < bounds.x0 - 0.5 or box.y0 < bounds.y0 - 0.5 or box.x1 > bounds.x1 + 0.5 or box.y1 > bounds.y1 + 0.5:
            outside.append(artist.get_text())
    assert not outside, outside
    fig.savefig(OUT / "Fig03_numerical_agreement.png", dpi=600)
    fig.savefig(OUT / "Fig03_numerical_agreement.svg")
    plt.close(fig)
    with Image.open(OUT / "Fig03_numerical_agreement.png") as picture:
        image = np.asarray(picture.convert("RGB"))
        ink_fraction = float(np.mean(np.any(image < 235, axis=2)))
        dimensions = picture.size
    assert ink_fraction > 0.01
    cases = pd.read_csv(inputs[3])
    assert cases.source_association_numerator.sum() == cases.source_association_denominator.sum() == 19000
    assert list(cases[cases.stage.str.startswith("real_A")].physical_unit_present_numerator) == [200, 200]
    qa = {
        "new_experiments_run": False,
        "original_results_modified": False,
        "real_continuous_comparisons": len(finite),
        "variable_statistic_groups": len(maxima),
        "comparisons_per_group": 198,
        "maximum_normalized_error": float(finite.normalized_error.max()),
        "all_continuous_within_tolerance": bool((finite.normalized_error <= 1).all()),
        "nonempty_count_exact_matches": len(counts),
        "controlled": summary.to_dict(orient="records"),
        "controlled_total_passed": int(controlled.passed.sum()),
        "controlled_total_checks": len(controlled),
        "controlled_groups_are_descriptive_not_independent_random_samples": True,
        "text_outside_canvas": outside,
        "png_pixels": dimensions,
        "ink_fraction": ink_fraction,
        "input_sha256": {str(path.relative_to(ROOT)): hashlib.sha256(path.read_bytes()).hexdigest() for path in inputs},
    }
    (OUT / "figure_qa.json").write_text(json.dumps(qa, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(qa, ensure_ascii=True))


if __name__ == "__main__":
    main()
