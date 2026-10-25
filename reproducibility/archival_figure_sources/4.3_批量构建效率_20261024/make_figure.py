"""Plot runtime and process RSS from completed benchmarks; do not rerun them."""

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
from matplotlib.text import Text
from PIL import Image


ROOT = Path(__file__).resolve().parents[2]
OUT = Path(__file__).resolve().parent
SOURCE = ROOT / "experiments/2026-10-16/results/benchmarks_protocol/all_measurements.json"
EARLIER = ROOT / "03修订稿_EMS精简版/论文数据分析图_20261022/plot_data/Fig08_Fig09_benchmark_summary.csv"


def main() -> None:
    raw = json.loads(SOURCE.read_text(encoding="utf-8"))
    assert len(raw) == 36
    assert all(run["exit_code"] == 0 and run["workflow_completed"] and not run["errors"] for run in raw)
    frame = pd.DataFrame(raw)
    assert not frame.duplicated(["n_objects", "n_rasters", "repeat"]).any()
    assert set(frame["repeat"]) == {0, 1, 2, 3}
    assert (frame.base_result_units == frame.n_objects * frame.n_rasters * 6).all()
    frame["peak_rss_mib"] = frame.peak_rss_bytes / 2**20
    frame["statistics_share"] = frame.statistics_seconds / (frame.statistics_seconds + frame.build_seconds)
    first = frame[frame["repeat"] == 0].copy()
    measured = frame[frame["repeat"] > 0].copy()
    assert len(first) == 9 and len(measured) == 27
    records = []
    for (objects, rasters), group in measured.groupby(["n_objects", "n_rasters"], sort=True):
        assert len(group) == 3
        record = {"objects": int(objects), "rasters": int(rasters), "repetitions": 3}
        for metric in ("workflow_seconds", "statistics_seconds", "build_seconds", "peak_rss_mib", "statistics_share"):
            record[f"{metric}_median"] = float(group[metric].median())
            record[f"{metric}_min"] = float(group[metric].min())
            record[f"{metric}_max"] = float(group[metric].max())
        for key in ("base_result_units", "derived_units", "units_created", "output_bytes"):
            assert group[key].nunique() == 1
            record[key] = int(group.iloc[0][key])
        records.append(record)
    summary = pd.DataFrame(records)
    assert len(summary) == 9
    old = pd.read_csv(EARLIER).sort_values(["n_objects", "n_rasters"])
    assert np.allclose(summary.workflow_seconds_median, old.workflow_seconds_median, rtol=0, atol=1e-10)
    assert np.allclose(summary.peak_rss_mib_median, old.peak_rss_MiB_median, rtol=0, atol=1e-8)
    assert np.allclose(summary.statistics_share_median, old.statistics_stage_share_median, rtol=0, atol=1e-10)
    data_dir = OUT / "plot_data"
    supplement = OUT / "supplementary"
    data_dir.mkdir(parents=True, exist_ok=True)
    supplement.mkdir(parents=True, exist_ok=True)
    summary.to_csv(data_dir / "runtime_memory_summary.csv", index=False, encoding="utf-8-sig")
    measured.to_csv(data_dir / "subsequent_27_runs.csv", index=False, encoding="utf-8-sig")
    first.to_csv(data_dir / "excluded_first_9_runs.csv", index=False, encoding="utf-8-sig")
    summary.to_csv(supplement / "TableS2_performance_summary.csv", index=False, encoding="utf-8-sig")

    plt.rcParams.update({
        "font.family": "Arial", "font.size": 8,
        "axes.labelsize": 8, "axes.linewidth": 0.6,
        "xtick.labelsize": 7.5, "ytick.labelsize": 7.5,
        "xtick.major.size": 3, "ytick.major.size": 3,
        "xtick.major.width": 0.6, "ytick.major.width": 0.6,
        "text.color": "#202020", "axes.labelcolor": "#202020",
        "xtick.color": "#303030", "ytick.color": "#303030",
        "svg.fonttype": "none", "savefig.facecolor": "white",
    })
    fig = plt.figure(figsize=(180 / 25.4, 86 / 25.4), facecolor="white")
    left = fig.add_axes([0.105, 0.205, 0.355, 0.56])
    right = fig.add_axes([0.615, 0.205, 0.355, 0.56])
    styles = {
        1: ("1 raster", "o", "#356887"),
        3: ("3 rasters", "s", "#4C8270"),
        5: ("5 rasters", "^", "#AB7839"),
    }
    for raster_count, (label, marker, color) in styles.items():
        group = summary[summary.rasters == raster_count].sort_values("objects")
        x = group.objects.to_numpy()
        for ax, metric in ((left, "workflow_seconds"), (right, "peak_rss_mib")):
            median = group[f"{metric}_median"].to_numpy()
            low = group[f"{metric}_min"].to_numpy()
            high = group[f"{metric}_max"].to_numpy()
            ax.errorbar(x, median, yerr=np.vstack([median - low, high - median]),
                        color=color, marker=marker, markersize=4, linewidth=1,
                        elinewidth=0.65, capsize=2, capthick=0.65,
                        markeredgewidth=0.6, label=label, zorder=3)
    for ax in (left, right):
        ax.set_xlim(40, 1090)
        ax.set_xticks([100, 500, 1000], ["100", "500", "1,000"])
        ax.set_xlabel("Number of basin objects", labelpad=7)
        ax.spines[["top", "right"]].set_visible(False)
        ax.spines["left"].set_color("#606060")
        ax.spines["bottom"].set_color("#606060")
        ax.grid(axis="y", color="#E7E7E7", linewidth=0.4, zorder=0)
    left.set_ylim(0, 10.6)
    left.set_yticks([0, 2, 4, 6, 8, 10])
    left.set_ylabel("Workflow time (s)", labelpad=7)
    right.set_ylim(150, 286)
    right.set_yticks([160, 200, 240, 280])
    right.set_ylabel("Peak process RSS (MiB)", labelpad=7)
    fig.text(0.055, 0.965, "(a) Processing time", fontsize=9, weight="bold", va="top")
    fig.text(0.565, 0.965, "(b) Memory use", fontsize=9, weight="bold", va="top")
    handles = [Line2D([], [], color=color, marker=marker, linewidth=1, markersize=4, label=label)
               for label, marker, color in styles.values()]
    fig.legend(handles=handles, loc="upper center", bbox_to_anchor=(0.54, 0.88),
               ncol=3, frameon=False, fontsize=7.8, handlelength=1.7,
               handletextpad=0.55, columnspacing=2.0, borderaxespad=0)
    largest = summary[(summary.objects == 1000) & (summary.rasters == 5)].iloc[0]
    left.annotate(f"{largest.workflow_seconds_median:.3f} s",
                  (1000, largest.workflow_seconds_median), xytext=(-5, 8),
                  textcoords="offset points", ha="right", va="bottom", fontsize=7.7, color="#8D602A")
    right.annotate(f"{largest.peak_rss_mib_median:.1f} MiB",
                   (1000, largest.peak_rss_mib_median), xytext=(-5, 8),
                   textcoords="offset points", ha="right", va="bottom", fontsize=7.7, color="#8D602A")

    fig.canvas.draw()
    renderer = fig.canvas.get_renderer()
    canvas = fig.bbox
    outside = []
    for artist in fig.findobj(Text):
        if not artist.get_visible() or not artist.get_text():
            continue
        box = artist.get_window_extent(renderer)
        if box.x0 < canvas.x0 - 0.5 or box.y0 < canvas.y0 - 0.5 or box.x1 > canvas.x1 + 0.5 or box.y1 > canvas.y1 + 0.5:
            outside.append(artist.get_text())
    assert not outside, outside
    fig.savefig(OUT / "Fig04_runtime_memory.png", dpi=600)
    fig.savefig(OUT / "Fig04_runtime_memory.svg")
    plt.close(fig)
    with Image.open(OUT / "Fig04_runtime_memory.png") as picture:
        ink_fraction = float(np.mean(np.any(np.asarray(picture.convert("RGB")) < 235, axis=2)))
        dimensions = picture.size
    assert ink_fraction > 0.01

    lines = [
        "补充表S2 不同对象数与栅格数组合的处理效率",
        "数值为每种组合首次记录后3次独立进程运行的中位数。",
        "对象数  栅格数  统计/s  构建/s  全流程/s  基础记录  派生记录  总记录  峰值RSS/MiB",
    ]
    for _, row in summary.iterrows():
        lines.append(
            f"{int(row.objects):>6}  {int(row.rasters):>6}  "
            f"{row.statistics_seconds_median:>6.3f}  {row.build_seconds_median:>6.3f}  "
            f"{row.workflow_seconds_median:>8.3f}  {int(row.base_result_units):>8}  "
            f"{int(row.derived_units):>8}  {int(row.units_created):>6}  {row.peak_rss_mib_median:>12.1f}"
        )
    lines += [
        "", "统计与构建阶段分别取中位数，不要求其和严格等于完整流程耗时的中位数。",
        "RSS为整个进程以50 ms间隔抽样获得的绝对峰值，而非相对于解释器基线的净增内存。",
        "操作系统文件缓存未清空或控制。CSV版本保留全部指标的最小值、中位数与最大值。",
    ]
    (supplement / "TableS2_performance_summary.txt").write_text("\n".join(lines), encoding="utf-8")
    qa = {
        "new_experiments_run": False,
        "original_results_modified": False,
        "completed_original_runs": len(raw),
        "combinations": len(summary),
        "subsequent_runs_plotted": len(measured),
        "first_runs_excluded": len(first),
        "summary_matches_existing_results": True,
        "error_bars": "observed minimum to maximum of three subsequent runs; not confidence intervals",
        "rss": "sampled absolute process peak, 50 ms interval, summarized by median",
        "cache": "not flushed or controlled",
        "stage_share_group_medians_min": float(summary.statistics_share_median.min()),
        "stage_share_group_medians_max": float(summary.statistics_share_median.max()),
        "largest_case": largest.to_dict(),
        "png_pixels": dimensions,
        "text_outside_canvas": outside,
        "ink_fraction": ink_fraction,
        "input_sha256": {str(path.relative_to(ROOT)): hashlib.sha256(path.read_bytes()).hexdigest() for path in (SOURCE, EARLIER)},
    }
    (OUT / "figure_qa.json").write_text(json.dumps(qa, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(qa, ensure_ascii=True))


if __name__ == "__main__":
    main()
