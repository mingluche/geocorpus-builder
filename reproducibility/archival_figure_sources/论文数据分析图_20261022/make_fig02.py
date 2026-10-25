"""Draw manuscript Figure 2 from the saved basin sampling data."""
from pathlib import Path
import argparse
import json

import geopandas as gpd
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.lines import Line2D
from matplotlib.patches import Patch, Polygon, Rectangle
from matplotlib.ticker import FuncFormatter, LogLocator, NullFormatter
import numpy as np
import pandas as pd
from pyproj import Geod

OUT = Path(__file__).resolve().parents[1]
BASE_COLOUR = "#3F5F73"
REUSE_COLOUR = "#995A54"
INK = "#222222"


def parallel_endpoint(geod, longitude, latitude, distance_m):
    """Find an endpoint at the scale-bar latitude with a given geodesic distance."""
    low, high = longitude, longitude + 35.0
    for _ in range(64):
        midpoint = (low + high) / 2
        distance = geod.inv(longitude, latitude, midpoint, latitude)[2]
        if distance < distance_m:
            low = midpoint
        else:
            high = midpoint
    return (low + high) / 2


def draw_scale_bar(ax):
    geod = Geod(ellps="WGS84")
    lon0, latitude = 124.0, 4.5
    distances_km = [0, 1000, 2000]
    longitudes = [lon0] + [
        parallel_endpoint(geod, lon0, latitude, km * 1000)
        for km in distances_km[1:]
    ]
    height = 0.72
    for i, (x0, x1) in enumerate(zip(longitudes[:-1], longitudes[1:])):
        ax.add_patch(Rectangle(
            (x0, latitude - height / 2), x1 - x0, height,
            facecolor=INK if i == 0 else "white", edgecolor=INK,
            linewidth=0.65, zorder=8,
        ))
    for x, label in zip(longitudes, ["0", "1,000", "2,000 km"]):
        ax.text(x, latitude - 1.05, label, ha="center", va="top",
                fontsize=7.1, color=INK, zorder=9)
    measured = [geod.inv(lon0, latitude, lon, latitude)[2] / 1000
                for lon in longitudes]
    assert np.allclose(measured, distances_km, atol=1e-6)
    return {"ellipsoid": "WGS84", "reference_latitude_deg": latitude,
            "longitude_ticks_deg": longitudes, "distance_ticks_km": measured}


def draw_north_arrow(ax):
    # Geographic coordinates: meridians run parallel to the vertical map frame.
    x, y, width, height = 0.91, 0.79, 0.033, 0.12
    tip = (x, y + height)
    notch = (x, y + 0.035)
    for vertices, face in [
        ([tip, (x - width / 2, y), notch], INK),
        ([tip, notch, (x + width / 2, y)], "white"),
    ]:
        ax.add_patch(Polygon(vertices, closed=True, transform=ax.transAxes,
                             facecolor=face, edgecolor=INK, linewidth=0.7, zorder=9))
    ax.text(x, y + height + 0.025, "N", transform=ax.transAxes,
            ha="center", va="bottom", fontsize=10, color=INK)


def render_figure02(eligible, prepared, samples, out=OUT):
    out = Path(out)
    for folder in ["png", "svg", "pdf", "qa"]:
        (out / folder).mkdir(parents=True, exist_ok=True)
    assert len(eligible) == 2351
    selected = prepared.loc[prepared.cohort.isin(["base", "reuse"])].copy()
    assert selected.groupby("cohort").size().to_dict() == {"base": 100, "reuse": 100}
    assert selected.region_id.nunique() == 200
    assert eligible.crs.is_geographic
    assert selected.crs == eligible.crs
    style = {
        "font.family": "Arial", "font.size": 9,
        "axes.labelsize": 9, "xtick.labelsize": 8, "ytick.labelsize": 8,
        "axes.edgecolor": INK, "axes.labelcolor": INK,
        "text.color": INK, "xtick.color": INK, "ytick.color": INK,
        "axes.linewidth": 0.65,
        "axes.spines.top": True, "axes.spines.right": True,
        "figure.facecolor": "white", "axes.facecolor": "white",
        "savefig.facecolor": "white", "svg.fonttype": "none", "pdf.fonttype": 42,
    }
    with plt.rc_context(style):
        fig = plt.figure(figsize=(10.8, 4.8))
        gs = fig.add_gridspec(1, 2, width_ratios=[1.64, 1.0], wspace=0.30)
        a, b = [fig.add_subplot(gs[0, i]) for i in range(2)]
        eligible.plot(ax=a, color="#EFEFEF", edgecolor="#CBCBCB",
                      linewidth=0.16, zorder=1)
        cohorts = [("base", BASE_COLOUR, "o"), ("reuse", REUSE_COLOUR, "^")]
        for cohort, colour, marker in cohorts:
            ss = selected.loc[selected.cohort == cohort]
            ss.plot(ax=a, color=colour, edgecolor=colour, linewidth=0.22,
                    alpha=0.36, zorder=2)
            rp = ss.geometry.representative_point()
            a.scatter(rp.x, rp.y, s=12 if marker == "o" else 17,
                      c=colour, marker=marker, edgecolors="white",
                      linewidths=0.23, zorder=3)
        a.set_xlim(55, 155)
        a.set_ylim(-2, 60)
        a.set_aspect(1 / np.cos(np.deg2rad(28)))
        a.set_xticks([60, 90, 120, 150])
        a.set_yticks([0, 20, 40, 60])
        a.xaxis.set_major_formatter(FuncFormatter(lambda v, p: f"{v:.0f}°E"))
        a.yaxis.set_major_formatter(FuncFormatter(lambda v, p: f"{v:.0f}°N"))
        a.set_xlabel("Longitude")
        a.set_ylabel("Latitude", labelpad=5)
        a.tick_params(direction="out", length=3, width=0.65)
        for spine in a.spines.values():
            spine.set_visible(True)
            spine.set_linewidth(0.65)
        a.set_title("(a)  Spatial distribution", loc="left", fontsize=10,
                    fontweight="normal", pad=10)
        handles = [
            Patch(facecolor="#EFEFEF", edgecolor="#BEBEBE",
                  linewidth=0.5, label="Eligible basins (n = 2,351)"),
            Line2D([], [], marker="o", linestyle="", color=BASE_COLOUR,
                   markeredgecolor="white", markeredgewidth=0.25,
                   label="Base (n = 100)", markersize=4.8),
            Line2D([], [], marker="^", linestyle="", color=REUSE_COLOUR,
                   markeredgecolor="white", markeredgewidth=0.25,
                   label="Reuse (n = 100)", markersize=5.0),
        ]
        a.legend(handles=handles, loc="lower left", bbox_to_anchor=(0.012, 0.018),
                 frameon=False, fontsize=7.7, handlelength=1.15,
                 borderaxespad=0, handletextpad=0.55, labelspacing=0.45)
        scale = draw_scale_bar(a)
        draw_north_arrow(a)

        b.scatter(eligible.SUB_AREA, eligible.ele_mt_sav, s=7,
                  color="#C8C8C8", alpha=0.60, edgecolors="none", zorder=1)
        for cohort, colour, marker in cohorts:
            ss = samples.loc[samples.cohort == cohort]
            b.scatter(ss.SUB_AREA, ss.ele_mt_sav, s=19 if marker == "o" else 23,
                      c=colour, marker=marker, alpha=0.90,
                      edgecolors="white", linewidths=0.30, zorder=3)
        b.set_xscale("log")
        b.set_xlim(0.07, 150000)
        b.set_ylim(-100, 6000)
        b.set_xticks([0.1, 10, 1000, 100000])
        b.set_xticklabels(["0.1", "10", "1,000", "100,000"])
        b.xaxis.set_minor_locator(LogLocator(base=10, subs=[1.0]))
        b.xaxis.set_minor_formatter(NullFormatter())
        b.set_yticks([0, 1500, 3000, 4500, 6000])
        b.yaxis.set_major_formatter(FuncFormatter(lambda v, p: f"{v:,.0f}"))
        b.set_xlabel("Basin area (km²)", labelpad=6)
        b.set_ylabel("Mean elevation (m)", labelpad=5)
        b.tick_params(direction="out", length=3, width=0.65)
        b.tick_params(which="minor", direction="out", length=1.8, width=0.5)
        b.grid(False)
        for spine in b.spines.values():
            spine.set_visible(True)
            spine.set_linewidth(0.65)
        b.set_title("(b)  Basin area and elevation", loc="left", fontsize=10,
                    fontweight="normal", pad=10)
        fig.subplots_adjust(left=0.063, right=0.985, bottom=0.16, top=0.91)
        for extension in ["png", "svg", "pdf"]:
            options = {"dpi": 400} if extension == "png" else {}
            fig.savefig(out / extension / f"Fig02_case_study_sampling.{extension}",
                        bbox_inches="tight", pad_inches=0.08, **options)
        plt.close(fig)

    metadata = {
        "panels": ["Spatial distribution", "Basin area and elevation"],
        "eligible_basins": len(eligible), "base_n": 100, "reuse_n": 100,
        "base_colour": BASE_COLOUR, "reuse_colour": REUSE_COLOUR,
        "base_marker": "circle", "reuse_marker": "triangle",
        "scale_bar": scale,
    }
    (out / "qa" / "Fig02_revision.json").write_text(
        json.dumps(metadata, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return metadata


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=OUT.parents[1])
    parser.add_argument("--out", type=Path, default=OUT)
    args = parser.parse_args()
    experiment = args.root / "experiments/2026-10-16"
    vector = experiment / "data/derived/basinatlas_asia_level6/BasinATLAS_v10_lev06_asia.shp"
    real = experiment / "results/real_protocol_main"
    all_basins = gpd.read_file(vector, columns=["HYBAS_ID", "SUB_AREA", "ele_mt_sav"])
    eligible = all_basins.loc[all_basins.geometry.is_valid].copy()
    prepared = gpd.read_file(real / "prepared/prepared_vector.gpkg",
                             columns=["region_id", "cohort", "SUB_AREA", "ele_mt_sav"])
    samples = pd.read_csv(real / "prepared/sample_membership.csv")
    assert len(all_basins) == 2489
    metadata = render_figure02(eligible, prepared, samples, args.out)
    print(json.dumps(metadata, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
