"""A named, Times New Roman example using the existing Nam Co basin data."""

from __future__ import annotations

import contextlib
import hashlib
import json
import sys
import textwrap
from dataclasses import asdict
from pathlib import Path

import geopandas as gpd
import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import rasterio
from matplotlib import font_manager
from matplotlib.colors import LightSource, LinearSegmentedColormap, Normalize
from matplotlib.lines import Line2D
from matplotlib.patches import PathPatch
from matplotlib.path import Path as MplPath
from matplotlib.text import Text
from matplotlib.ticker import FuncFormatter
from PIL import Image
from pyproj import Geod
from rasterio.windows import bounds as window_bounds
from rasterio.windows import from_bounds
from shapely import contains_xy, intersects_xy
from shapely.geometry import Point


ROOT = Path(__file__).resolve().parents[2]
OUT = Path(__file__).resolve().parent
REPO = ROOT / "geocorpus-builder"
EXPERIMENT = ROOT / "experiments/2026-10-16"
VECTOR = EXPERIMENT / "results/real_protocol_main/prepared/prepared_vector.gpkg"
SOURCE = EXPERIMENT / "results/benchmarks_protocol/n1000_m5_r1/project/statistics/v04_wc2.1_2.5m_elev.csv"
BASIN_ID = "R_4060050910"
DISPLAY_NAME = "Nam Co basin"
STEM = "namco_elevation"
sys.path.insert(0, str(REPO / "src"))

from geocorpus_builder.builder.engine import BuildOrchestrator
from geocorpus_builder.config.project import GeoCorpusProject
from geocorpus_builder.config.settings import GeoCorpusSettings


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def software_hashes() -> dict[str, str]:
    paths = sorted((REPO / "src").rglob("*.py")) + [REPO / "pyproject.toml"]
    return {str(path.relative_to(REPO)): digest(path) for path in paths}


def jsonl(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def build_example(index: int, record: dict) -> dict:
    template = [
        "The ${region_name} has a mean elevation of ${value} ${source_unit}.",
        "Mean elevation in the ${region_name} is ${value} ${source_unit}.",
    ][index - 1]
    project = OUT / "example_projects" / f"template_{index}"
    corpus_path = project / "corpus/corpus_units.jsonl"
    if not corpus_path.exists():
        (project / "statistics").mkdir(parents=True, exist_ok=True)
        (project / "templates").mkdir(exist_ok=True)
        pd.DataFrame([record]).to_csv(project / "statistics" / f"{STEM}.csv", index=False)
        (project / "templates/generic_stat.txt").write_text(template, encoding="utf-8")
        settings = GeoCorpusSettings(build_profile="auto", language="en", domain="environmental_data")
        (project / "geocorpus_config.json").write_text(settings.model_dump_json(indent=2), encoding="utf-8")
        with (project / "build.log").open("w", encoding="utf-8") as log:
            with contextlib.redirect_stdout(log), contextlib.redirect_stderr(log):
                report = BuildOrchestrator(GeoCorpusProject(root=project, config=settings)).build(
                    spatial_enrich=False, id_prefix="GC_EXAMPLE")
        (project / "build_report.json").write_text(json.dumps(asdict(report), indent=2), encoding="utf-8")
        assert not report.errors
    assert (project / "templates/generic_stat.txt").read_text(encoding="utf-8") == template
    units = jsonl(corpus_path)
    evidence_path = project / "evidence/evidence_links.jsonl"
    evidence = jsonl(evidence_path)
    assert len(units) == len(evidence) == 1
    assert units[0]["evidence_ids"] == [evidence[0]["evidence_id"]]
    assert evidence[0]["source_id"] == BASIN_ID
    assert float(evidence[0]["value"]) == float(record["mean"])
    assert DISPLAY_NAME in units[0]["text"] and " m." in units[0]["text"]
    return {"project": project, "unit": units[0], "evidence": evidence[0], "evidence_path": evidence_path}


def rule(fig, x0, x1, y, color="#A6ADB0", linewidth=0.55):
    fig.add_artist(Line2D([x0, x1], [y, y], transform=fig.transFigure, color=color, linewidth=linewidth))


def main() -> None:
    before = software_hashes()
    data_dir = OUT / "plot_data"
    data_dir.mkdir(parents=True, exist_ok=True)
    source = pd.read_csv(SOURCE, float_precision="round_trip")
    selected_row = source[source.region_id == BASIN_ID]
    assert len(selected_row) == 1
    row = selected_row.iloc[0]
    basins = gpd.read_file(VECTOR, layer="samples")
    selected = basins[basins.region_id == BASIN_ID]
    assert len(selected) == 1 and selected.geometry.is_valid.all()
    geometry = selected.iloc[0].geometry
    assert geometry.covers(Point(90.6, 30.7))
    assert int(selected.iloc[0].ENDO) == 2
    assert int(selected.iloc[0].HYBAS_ID) == int(selected.iloc[0].MAIN_BAS) == 4060050910
    selected[["HYBAS_ID", "SUB_AREA", "ENDO", "geometry"]].to_file(data_dir / "namco_boundary.gpkg", layer="basin", driver="GPKG")
    selected_row.to_csv(data_dir / "original_benchmark_row.csv", index=False, encoding="utf-8-sig")
    manifest = json.loads((EXPERIMENT / "data/real_case_manifest.json").read_text(encoding="utf-8"))
    spec = next(item for item in manifest["rasters"] if item["variable"] == "elevation")
    raster = EXPERIMENT / "data" / spec["path"]
    west, south, east, north = geometry.bounds
    pad_x, pad_y = (east - west) * 0.075, (north - south) * 0.10
    with rasterio.open(raster) as dataset:
        window = from_bounds(west - pad_x, south - pad_y, east + pad_x, north + pad_y,
                             dataset.transform).round_offsets().round_lengths()
        array = dataset.read(1, window=window, masked=True)
        transform = dataset.window_transform(window)
        extent_bounds = window_bounds(window, dataset.transform)
    rr, cc = np.indices(array.shape)
    xs = transform.c + (cc + 0.5) * transform.a
    ys = transform.f + (rr + 0.5) * transform.e
    inside = contains_xy(geometry, xs, ys)
    ties = intersects_xy(geometry, xs, ys) & ~inside
    valid = ~np.ma.getmaskarray(array) & np.isfinite(array.data)
    included = inside & valid
    values = array.data[included].astype(np.float64)
    assert not ties.any()
    assert len(values) == int(row["count"]) == 582
    references = {
        "mean": float(values.mean()), "median": float(np.median(values)),
        "std": float(values.std(ddof=0)), "min": float(values.min()), "max": float(values.max()),
    }
    assert all(abs(float(row[key]) - value) <= 5e-5 + 1e-6 * abs(value) for key, value in references.items())
    pd.DataFrame({"longitude": xs[included], "latitude": ys[included], "elevation_m": values}).to_csv(
        data_dir / "valid_pixel_centres.csv", index=False, encoding="utf-8-sig")
    record = {
        "region_id": BASIN_ID,
        "region_name": DISPLAY_NAME,
        "variable": "elevation",
        "time_range": "static (SRTM-derived)",
        "mean": float(row["mean"]),
        "source_unit": spec["unit"],
        "lon": float(row["lon"]), "lat": float(row["lat"]),
    }
    first, second = [build_example(index, record) for index in (1, 2)]
    assert digest(first["evidence_path"]) == digest(second["evidence_path"])
    assert {key for key in set(first["unit"]) | set(second["unit"])
            if first["unit"].get(key) != second["unit"].get(key)} == {"text"}
    named_provenance = {
        "display_name": DISPLAY_NAME,
        "source_object_id": BASIN_ID,
        "name_is_derived_display_metadata_not_original_basinatlas_name": True,
        "name_assignment": "Spatial association with the published Nam Co catchment extent and lake location; source unit is a closed terminal basin",
        "basinatlas_bounds": list(geometry.bounds),
        "basinatlas_area_km2": float(selected.iloc[0].SUB_AREA),
        "published_coordinate_extent": "89 deg 21 min to 91 deg 23 min E; 29 deg 56 min to 31 deg 7 min N",
        "references": [
            "https://doi.org/10.1080/02626667.2021.1957474",
            "https://doi.org/10.5194/essd-11-1603-2019",
            "https://doi.org/10.5194/adgeo-27-29-2010",
        ],
        "source_table": str(SOURCE.relative_to(ROOT)),
        "illustration_scope": "BasinATLAS delineation associated with the named catchment, not a substitute for the boundary from a different publication",
        "input_name_and_source_unit_explicitly_added_before_build": True,
        "unit_in_text": "source_unit field from the WorldClim input metadata, rendered by project template",
        "auto_builder_evidence_unit": first["evidence"]["unit"],
    }
    (data_dir / "name_provenance.json").write_text(json.dumps(named_provenance, ensure_ascii=False, indent=2), encoding="utf-8")
    example = {
        "input": record, "reference": references,
        "template_1_output": first["unit"], "template_2_output": second["unit"],
        "evidence": first["evidence"],
    }
    (data_dir / "example_records.json").write_text(json.dumps(example, ensure_ascii=False, indent=2), encoding="utf-8")

    font_path = font_manager.findfont("Times New Roman", fallback_to_default=False)
    plt.rcParams.update({
        "font.family": "Times New Roman", "font.size": 8.5,
        "axes.linewidth": 0.6, "axes.labelsize": 8.5,
        "xtick.labelsize": 7.5, "ytick.labelsize": 7.5,
        "xtick.major.size": 2.5, "ytick.major.size": 2.5,
        "xtick.major.width": 0.5, "ytick.major.width": 0.5,
        "text.color": "#20282B", "axes.labelcolor": "#20282B",
        "xtick.color": "#303030", "ytick.color": "#303030",
        "svg.fonttype": "none", "savefig.facecolor": "white",
        "axes.unicode_minus": False,
    })
    fig = plt.figure(figsize=(180 / 25.4, 118 / 25.4), facecolor="white")
    fig.text(0.055, 0.96, "(a) Nam Co basin", fontsize=11, weight="bold", va="top")
    fig.text(0.055, 0.916, "BasinATLAS delineation | Tibetan Plateau", fontsize=8.1, style="italic", color="#5B686B", va="top")
    fig.text(0.555, 0.96, "(b) Template-controlled statements", fontsize=10, weight="bold", va="top")
    rule(fig, 0.555, 0.965, 0.918)
    fig.text(0.565, 0.88, "Template 1", fontsize=8, style="italic", color="#5B686B", va="top")
    fig.text(0.565, 0.839, textwrap.fill(first["unit"]["text"], width=43),
             fontsize=10.4, linespacing=1.3, va="top")
    fig.text(0.565, 0.704, "Template 2", fontsize=8, style="italic", color="#5B686B", va="top")
    fig.text(0.565, 0.663, textwrap.fill(second["unit"]["text"], width=43),
             fontsize=10.4, linespacing=1.3, va="top")
    fig.text(0.565, 0.546, "Shared evidence reference: EV_0001", fontsize=8, color="#365F70", va="top")

    map_ax = fig.add_axes([0.055, 0.345, 0.425, 0.535])
    west, south, east, north = extent_bounds
    extent = (west, east, south, north)
    elevation = np.asarray(array.filled(float(np.median(values))), dtype=float)
    background = Normalize(4500, 6500)(elevation)
    map_ax.imshow(background, extent=extent, origin="upper", cmap="Greys", vmin=0, vmax=1,
                  alpha=0.16, interpolation="bilinear", zorder=0)
    cmap = LinearSegmentedColormap.from_list("muted_terrain", plt.get_cmap("gist_earth")(np.linspace(0.32, 0.94, 256)))
    norm = Normalize(4700, 6100)
    rgb = cmap(norm(elevation))[:, :, :3]
    lat_center = (south + north) / 2
    dx = abs(transform.a) * 111320 * np.cos(np.radians(lat_center))
    dy = abs(transform.e) * 111320
    shade = LightSource(azdeg=315, altdeg=45).hillshade(elevation, vert_exag=3, dx=dx, dy=dy)
    rgb = np.clip(rgb * (0.64 + 0.36 * shade[..., None]), 0, 1)
    polygon_paths = []
    for polygon in geometry.geoms if geometry.geom_type == "MultiPolygon" else [geometry]:
        for ring in [polygon.exterior, *polygon.interiors]:
            vertices = np.asarray(ring.coords)
            codes = np.full(len(vertices), MplPath.LINETO, dtype=np.uint8)
            codes[0], codes[-1] = MplPath.MOVETO, MplPath.CLOSEPOLY
            polygon_paths.append(MplPath(vertices, codes))
    clip = PathPatch(MplPath.make_compound_path(*polygon_paths), transform=map_ax.transData,
                     facecolor="none", edgecolor="none")
    map_ax.add_patch(clip)
    terrain_image = map_ax.imshow(rgb, extent=extent, origin="upper", interpolation="bilinear", zorder=1)
    terrain_image.set_clip_path(clip)
    contours = map_ax.contour(xs, ys, elevation, levels=[4800, 5200, 5600],
                             colors="white", linewidths=0.35, alpha=0.55, zorder=2)
    contours.set_clip_path(clip)
    for polygon in geometry.geoms if geometry.geom_type == "MultiPolygon" else [geometry]:
        x, y = polygon.exterior.xy
        map_ax.plot(x, y, color="#263C45", linewidth=0.85, zorder=3)
        for ring in polygon.interiors:
            x, y = ring.xy
            map_ax.plot(x, y, color="#263C45", linewidth=0.5, zorder=3)
    map_ax.set_xlim(west, east)
    map_ax.set_ylim(south, north)
    map_ax.set_aspect(1 / np.cos(np.radians(lat_center)))
    map_ax.set_xticks([89.5, 90.0, 90.5, 91.0])
    map_ax.set_yticks([30.0, 30.5, 31.0])
    map_ax.xaxis.set_major_formatter(FuncFormatter(lambda value, _: f"{value:.1f}°E"))
    map_ax.yaxis.set_major_formatter(FuncFormatter(lambda value, _: f"{value:.1f}°N"))
    map_ax.annotate("", xy=(0.93, 0.89), xytext=(0.93, 0.73), xycoords="axes fraction",
                    arrowprops={"arrowstyle": "-|>", "lw": 0.7, "color": "#263C45"})
    map_ax.text(0.93, 0.93, "N", transform=map_ax.transAxes, ha="center", va="center", fontsize=8)
    scale_x, scale_y = west + 0.07 * (east - west), south + 0.09 * (north - south)
    scale_end, _, _ = Geod(ellps="WGS84").fwd(scale_x, scale_y, 90, 20000)
    map_ax.plot([scale_x, scale_end], [scale_y, scale_y], color="#263C45", linewidth=1.5)
    map_ax.text((scale_x + scale_end) / 2, scale_y + (north - south) * 0.025,
                "20 km", ha="center", va="bottom", fontsize=7)
    color_ax = fig.add_axes([0.067, 0.289, 0.401, 0.014])
    colorbar = fig.colorbar(plt.cm.ScalarMappable(norm=norm, cmap=cmap), cax=color_ax,
                          orientation="horizontal", ticks=[4700, 5100, 5500, 5900, 6100])
    colorbar.outline.set_linewidth(0.5)
    colorbar.ax.tick_params(labelsize=7, width=0.5, length=2, pad=2)
    colorbar.set_label("Elevation (m)", fontsize=8, labelpad=3)
    rule(fig, 0.055, 0.48, 0.208)
    left_rows = [
        ("Mean elevation", f"{float(row['mean']):.4f} m"),
        ("Standard deviation", f"{float(row['std']):.4f} m"),
        ("Valid raster cells", str(int(row["count"]))),
    ]
    for index, (key, value) in enumerate(left_rows):
        y = 0.181 - index * 0.041
        fig.text(0.063, y, key, fontsize=8.3, va="top")
        fig.text(0.472, y, value, fontsize=8.5, ha="right", va="top",
                 color="#365F70" if index == 0 else "#20282B")
    rule(fig, 0.055, 0.48, 0.068)

    fig.text(0.555, 0.475, "(c) Linked numerical evidence", fontsize=10, weight="bold", va="top")
    rule(fig, 0.555, 0.965, 0.433)
    evidence = first["evidence"]
    fields = [
        ("Evidence ID", evidence["evidence_id"]),
        ("Corpus ID", evidence["corpus_id"]),
        ("Source object", evidence["source_id"]),
        ("Variable", evidence["variable"]),
        ("Statistic", evidence["statistic"]),
        ("Value", evidence["value"]),
        ("Source table", evidence["source_table"]),
        ("Period", evidence["time_range"]),
    ]
    for index, (key, value) in enumerate(fields):
        y = 0.41 - index * 0.041
        fig.text(0.565, y, key, fontsize=8.1, color="#566469", va="top")
        fig.text(0.735, y, str(value), fontsize=8.4, va="top",
                 color="#365F70" if key in {"Evidence ID", "Value"} else "#20282B")
    rule(fig, 0.555, 0.965, 0.068)

    fig.canvas.draw()
    renderer = fig.canvas.get_renderer()
    outside = []
    families = set()
    for artist in fig.findobj(Text):
        if not artist.get_visible() or not artist.get_text():
            continue
        families.update(artist.get_fontfamily())
        box = artist.get_window_extent(renderer)
        if box.x0 < -0.5 or box.y0 < -0.5 or box.x1 > fig.bbox.x1 + 0.5 or box.y1 > fig.bbox.y1 + 0.5:
            outside.append(artist.get_text())
    assert not outside, outside
    assert families == {"Times New Roman"}, families
    fig.savefig(OUT / "Fig03_NamCo_TimesNewRoman.png", dpi=600)
    fig.savefig(OUT / "Fig03_NamCo_TimesNewRoman.svg")
    plt.close(fig)
    with Image.open(OUT / "Fig03_NamCo_TimesNewRoman.png") as picture:
        dimensions = picture.size
        ink = float(np.mean(np.any(np.asarray(picture.convert("RGB")) < 235, axis=2)))
    assert ink > 0.02
    assert software_hashes() == before
    qa = {
        "font": "Times New Roman", "font_file": font_path, "all_visible_text_families": sorted(families),
        "named_object": DISPLAY_NAME, "source_id": BASIN_ID,
        "original_benchmark_mean": float(row["mean"]), "independent_reference": references,
        "valid_pixel_count": len(values), "boundary_tied_centres": int(ties.sum()),
        "both_english_outputs_actually_built": True,
        "texts": [first["unit"]["text"], second["unit"]["text"]],
        "only_text_differs_between_corpus_records": True,
        "evidence_files_byte_identical": True,
        "evidence_unit_not_silently_repaired": evidence["unit"],
        "unit_in_sentence_from_explicit_source_unit_template_field": True,
        "map_bilinear_rendering_only_statistics_use_original_cells": True,
        "original_software_unchanged_files": len(before), "source_sha256": before,
        "source_inputs_sha256": {str(path.relative_to(ROOT)): digest(path) for path in (SOURCE, VECTOR, raster)},
        "png_pixels": dimensions, "ink_fraction": ink, "text_outside_canvas": outside,
    }
    (OUT / "figure_qa.json").write_text(json.dumps(qa, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({key: value for key, value in qa.items() if key not in {"source_sha256", "source_inputs_sha256"}}, ensure_ascii=True))


if __name__ == "__main__":
    main()
