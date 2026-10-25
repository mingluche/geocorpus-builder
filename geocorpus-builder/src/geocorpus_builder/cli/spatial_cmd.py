"""geocorpus spatial -- manage and query bundled China geospatial data layers."""

import json
from pathlib import Path

import click
from rich.console import Console
from rich.table import Table

from ..spatial import SpatialQueryEngine
from ..spatial.importer import import_shapefile, import_directory


@click.group(name="spatial")
def spatial():
    """Manage and query bundled China geospatial data layers."""
    pass


# ---- import ----

@spatial.command(name="import")
@click.argument("shp_path", type=click.Path(exists=True))
@click.option("--layer", "-l", required=True, help="Layer ID (e.g. cn_provinces)")
@click.option("--layer-name", default="", help="Human-readable name")
@click.option("--layer-type", default="admin_boundary",
              type=click.Choice(["admin_boundary", "river_basin", "climate_zone",
                                 "terrain", "custom"]))
@click.option("--name-field", default="name_zh", help="Field containing region name")
@click.option("--id-field", default="adcode", help="Field containing unique region ID")
@click.option("--crs", default="EPSG:4326", help="Target coordinate reference system")
@click.option("--output-dir", "-o", type=click.Path(), default=None)
def _import(shp_path, layer, layer_name, layer_type, name_field, id_field, crs, output_dir):
    """Import a Shapefile and convert to GeoParquet."""
    out = Path(output_dir).resolve() if output_dir else None
    import_shapefile(
        shp_path=Path(shp_path),
        layer_id=layer,
        layer_name=layer_name or layer,
        layer_type=layer_type,
        name_field=name_field,
        id_field=id_field,
        crs=crs,
        output_dir=out,
    )
    click.echo(f"Layer '{layer}' imported successfully.")


@spatial.command(name="import-dir")
@click.argument("directory", type=click.Path(exists=True))
@click.option("--output-dir", "-o", type=click.Path(), default=None)
def _import_dir(directory, output_dir):
    """Import all .shp files in a directory."""
    out = Path(output_dir).resolve() if output_dir else None
    results = import_directory(Path(directory), output_dir=out)
    for meta in results:
        click.echo(f"  Imported: {meta.layer_id} ({meta.feature_count} features)")


# ---- list ----

@spatial.command(name="list")
def _list():
    """List all installed spatial data layers."""
    engine = SpatialQueryEngine()
    layers = engine.list_layers()
    rasters = engine.registry.list_rasters()

    if not layers and not rasters:
        click.echo("No spatial layers installed.")
        click.echo("Use 'geocorpus spatial import <shp>' to add vector layers.")
        click.echo("Use 'geocorpus spatial import-raster <file>' to add raster layers.")
        return

    console = Console()

    if layers:
        tbl = Table(title="Vector Layers")
        tbl.add_column("Layer ID", style="cyan")
        tbl.add_column("Name")
        tbl.add_column("Type")
        tbl.add_column("Features")
        tbl.add_column("Fields")
        tbl.add_column("Source")
        for meta in layers:
            tbl.add_row(
                meta.layer_id, meta.layer_name, meta.layer_type,
                str(meta.feature_count),
                ", ".join(meta.fields[:5]) + ("..." if len(meta.fields) > 5 else ""),
                meta.source,
            )
        console.print(tbl)

    if rasters:
        console.print()
        tbl2 = Table(title="Raster Layers (Fixed Grid)")
        tbl2.add_column("Raster ID", style="green")
        tbl2.add_column("Name")
        tbl2.add_column("Format")
        tbl2.add_column("Variable")
        tbl2.add_column("Time")
        tbl2.add_column("Grid", style="cyan")
        tbl2.add_column("Spatial Scale")
        tbl2.add_column("Size")
        for r in rasters:
            size_mb = r.get("size_bytes", 0) / 1024 / 1024
            grid_info = STANDARD_GRID_LEVELS.get(r.get("grid_level", ""), {})
            grid_desc = grid_info.get("description", "") if grid_info else ""
            grid_str = f"{r.get('grid_level', '?')}  ({grid_desc})"
            tbl2.add_row(
                r.get("raster_id", ""),
                r.get("layer_name", ""),
                r.get("format", "").upper(),
                r.get("variable", "-"),
                r.get("time_range", "-"),
                grid_str,
                r.get("spatial_scale", "-"),
                f"{size_mb:.1f} MB",
            )
            if r.get("bounds"):
                tbl2.add_row("", f"  bounds: {r['bounds']}", "", "", "", "", "", "")
        console.print(tbl2)

        if any(not r.get("grid_level") for r in rasters):
            console.print("\n[yellow]提示: 部分栅格未绑定网格级别，可通过 --grid-level 指定[/yellow]")


# Need STANDARD_GRID_LEVELS in scope for the _list function
from ..spatial.registry import STANDARD_GRID_LEVELS


# ---- locate ----

@spatial.command(name="locate")
@click.option("--lon", "-x", type=float, required=True, help="Longitude (WGS84)")
@click.option("--lat", "-y", type=float, required=True, help="Latitude (WGS84)")
@click.option("--layers", "-l", multiple=True, help="Specific layers to query")
@click.option("--format", "-f", "output_format", type=click.Choice(["table", "json"]),
              default="table")
def _locate(lon, lat, layers, output_format):
    """Find which regions contain a given point (lon, lat)."""
    engine = SpatialQueryEngine()
    result = engine.locate(lon, lat, layers=list(layers) if layers else None)

    if output_format == "json":
        click.echo(json.dumps(result, ensure_ascii=False, indent=2))
        return

    if not result:
        click.echo(f"No region found at ({lon}, {lat}).")
        return

    console = Console()
    tbl = Table(title=f"Region Location: ({lon}, {lat})")
    tbl.add_column("Layer", style="cyan")
    tbl.add_column("Region Name")
    tbl.add_column("ID")
    tbl.add_column("Fields")

    for layer_id, info in result.items():
        name = info.get("name_zh", info.get("layer_id", "?"))
        rid = info.get("adcode", info.get("id", "?"))
        extra = {k: v for k, v in info.items()
                 if k not in ("layer_id", "layer_name", "name_zh", "adcode")}
        tbl.add_row(layer_id, str(name), str(rid), json.dumps(extra, ensure_ascii=False))

    console.print(tbl)


# ---- neighbors ----

@spatial.command(name="neighbors")
@click.argument("region_id")
@click.option("--layer", "-l", required=True, help="Layer to query")
@click.option("--format", "-f", "output_format", type=click.Choice(["table", "json"]),
              default="table")
def _neighbors(region_id, layer, output_format):
    """Find neighboring regions of a given region."""
    engine = SpatialQueryEngine()
    results = engine.neighbors(region_id, layer)

    if output_format == "json":
        click.echo(json.dumps(results, ensure_ascii=False, indent=2))
        return

    if not results:
        click.echo(f"No neighbors found for region '{region_id}' in layer '{layer}'.")
        return

    console = Console()
    tbl = Table(title=f"Neighbors of {region_id} ({layer})")
    tbl.add_column("Region Name")
    tbl.add_column("ID")

    for r in results:
        name = r.get("name_zh", "?")
        rid = r.get("adcode", r.get("id", "?"))
        tbl.add_row(str(name), str(rid))

    console.print(tbl)
    click.echo(f"\n{len(results)} neighbor(s) found.")


# ---- overlap ----

@spatial.command(name="overlap")
@click.argument("geometry", required=False)
@click.option("--wkt", type=str, default=None, help="WKT geometry string")
@click.option("--layer", "-l", required=True, help="Target layer")
@click.option("--format", "-f", "output_format", type=click.Choice(["table", "json"]),
              default="table")
def _overlap(geometry, wkt, layer, output_format):
    """Calculate overlap between a geometry and target layer regions."""
    geom_input = wkt or geometry
    if not geom_input:
        raise click.UsageError("Provide a WKT string (--wkt) or a geometry file path.")

    geom_path = Path(geom_input)
    if geom_path.exists():
        geom_input = geom_path.read_text(encoding="utf-8").strip()

    engine = SpatialQueryEngine()
    results = engine.overlap(geom_input, layer)

    if output_format == "json":
        click.echo(json.dumps(results, ensure_ascii=False, indent=2))
        return

    if not results:
        click.echo("No overlap found.")
        return

    console = Console()
    tbl = Table(title=f"Overlap with {layer}")
    tbl.add_column("Region", style="cyan")
    tbl.add_column("Area Fraction", justify="right")
    tbl.add_column("Overlap (deg²)", justify="right")

    for r in results:
        name = r.get("name_zh", "?")
        tbl.add_row(str(name), f"{r['area_fraction']:.4f}", f"{r['overlap_area_m2']:.2f}")
    console.print(tbl)


# ---- distance ----

@spatial.command(name="distance")
@click.option("--geom-a", type=str, required=True, help="First geometry (WKT or file)")
@click.option("--geom-b", type=str, required=True, help="Second geometry (WKT or file)")
@click.option("--unit", type=click.Choice(["m", "km"]), default="km")
def _distance(geom_a, geom_b, unit):
    """Calculate distance between two geometries."""
    from shapely import wkt as wkt_parser

    def _load(g):
        p = Path(g)
        if p.exists():
            g = p.read_text(encoding="utf-8").strip()
        if g.upper().startswith(("POINT", "POLYGON", "LINESTRING", "MULTI")):
            return wkt_parser.loads(g)
        return None

    ga = _load(geom_a)
    gb = _load(geom_b)
    if ga is None or gb is None:
        raise click.BadParameter("Geometries must be valid WKT strings or files.")

    engine = SpatialQueryEngine()
    d_m = engine.distance(ga, gb)
    if unit == "km":
        click.echo(f"{d_m / 1000:.2f} km")
    else:
        click.echo(f"{d_m:.0f} m")


# ---- import-raster ----

@spatial.command(name="import-raster")
@click.argument("raster_path", type=click.Path(exists=True))
@click.option("--layer", "-l", required=True, help="Raster layer ID (e.g. dem_30m)")
@click.option("--layer-name", default="", help="Human-readable name")
@click.option("--variable", default="", help="Variable name (e.g. elevation)")
@click.option("--time-range", default="", help="Time range (e.g. 2024)")
@click.option("--grid-level", "-g", type=click.Choice(["30m","90m","250m","1km","5km","10km"]),
              default=None, help="Fixed grid level (auto-detect if omitted)")
@click.option("--spatial-scale", default="", help="Spatial scale (e.g. grid_30m, region)")
@click.option("--crs", default="EPSG:4326", help="Target CRS for standardization")
@click.option("--reproject", is_flag=True, default=False,
              help="Reproject to target CRS if source CRS differs")
@click.option("--notes", default="", help="Additional notes")
def _import_raster(raster_path, layer, layer_name, variable, time_range,
                    grid_level, spatial_scale, crs, reproject, notes):
    """Import a raster (TIFF/NC) into the fixed-grid spatial data system.

    Detects source CRS automatically. Use --reproject to convert to the
    target CRS (default EPSG:4326) if they differ. Without --reproject,
    the file is copied as-is and the CRS mismatch is recorded.

    \b
    Examples:
        geocorpus spatial import-raster dem.tif --layer dem_30m --reproject
        geocorpus spatial import-raster thick.tif --layer thick --crs EPSG:4490 --reproject
    """
    from ..spatial.registry import LayerRegistry
    registry = LayerRegistry()
    meta = {
        "layer_name": layer_name or layer,
        "variable": variable,
        "time_range": time_range,
        "notes": notes,
    }
    if spatial_scale:
        meta["spatial_scale"] = spatial_scale
    dest = registry.register_raster(layer, Path(raster_path), meta,
                                     grid_level=grid_level,
                                     target_crs=crs, reproject=reproject)
    full_meta = registry.get_raster_meta(layer)
    detected = full_meta.get("grid_level", "?") if full_meta else "?"
    src_crs = full_meta.get("source_crs", "?") if full_meta else "?"
    tgt_crs = full_meta.get("target_crs", "?") if full_meta else "?"
    was_reprojected = full_meta.get("reprojected", False) if full_meta else False
    reproj_note = " [reprojected]" if was_reprojected else ""
    if not was_reprojected and src_crs != tgt_crs:
        reproj_note = f" [WARN: source={src_crs}, target={tgt_crs} -- use --reproject to convert]"
    click.echo(f"Raster: {dest} ({dest.stat().st_size / 1024 / 1024:.1f} MB)"
               f" | Grid: {detected} | CRS: {src_crs}→{tgt_crs}{reproj_note}")


# ---- zonal-stats ----

@spatial.command(name="zonal-stats")
@click.option("--raster", "-r", type=click.Path(exists=True), required=True,
              help="Input GeoTIFF raster file")
@click.option("--vector", "-v", type=click.Path(exists=True), required=True,
              help="Input vector file (SHP/GeoJSON) with polygon boundaries")
@click.option("--output", "-o", type=click.Path(), required=True,
              help="Output CSV path for statistics")
@click.option("--id-field", default="glacier_id", help="Unique ID field in vector")
@click.option("--stats", default="mean,median,std,min,max,count",
              help="Comma-separated list of statistics to compute")
@click.option("--nodata", type=float, default=None, help="Override raster nodata value")
def _zonal_stats(raster, vector, output, id_field, stats, nodata):
    """Compute zonal statistics: raster values within each vector polygon.

    Reads a GeoTIFF raster and a polygon vector file. For each polygon,
    extracts the underlying raster pixels and computes statistics
    (mean, median, std, min, max, count).

    Output is a CSV with one row per polygon and one column per statistic,
    plus lon/lat of polygon centroids for spatial enrichment.

    Example:
        geocorpus spatial zonal-stats \\
            --raster thickness_2024.tif \\
            --vector glacier_boundaries.shp \\
            --output stats/thickness_2024.csv \\
            --id-field glacier_id
    """
    stats_list = [s.strip() for s in stats.split(",")]
    engine = SpatialQueryEngine()
    try:
        out_path = engine.zonal_stats(
            raster_path=Path(raster),
            vector_path=Path(vector),
            output_path=Path(output),
            id_field=id_field,
            stats_list=stats_list,
            nodata=nodata,
        )
        click.echo(f"Statistics written to: {out_path}")
    except ImportError as e:
        click.echo(str(e), err=True)
        raise SystemExit(1)


# ---- show ----

@spatial.command(name="show")
@click.argument("layers", type=str)
@click.option("--output", "-o", type=click.Path(), default=None,
              help="Output PNG path (default: ./spatial_map.png)")
@click.option("--title", "-t", default="", help="Map title")
@click.option("--point", "-p", type=str, default=None,
              help="Mark a point on the map (format: lon,lat)")
@click.option("--dpi", type=int, default=150, help="Output resolution")
def _show(layers, output, title, point, dpi):
    """Render spatial layers as a map PNG.

    LAYERS is a comma-separated list of layer IDs to display.

    \b
    Examples:
        geocorpus spatial show cn_sheng
        geocorpus spatial show cn_sheng,cn_tibetan_plateau -t "Tibetan Plateau"
        geocorpus spatial show cn_sheng -p 91.0,30.0 -o my_map.png
    """
    layer_list = [s.strip() for s in layers.split(",")]
    out = Path(output) if output else Path("spatial_map.png")

    engine = SpatialQueryEngine()

    pt = None
    if point:
        parts = point.split(",")
        if len(parts) == 2:
            pt = (float(parts[0].strip()), float(parts[1].strip()))

    try:
        result = engine.show(layer_list, out.resolve(), title=title, point=pt, dpi=dpi)
        click.echo(f"Map saved: {result}")
    except ImportError as e:
        click.echo(str(e), err=True)


# ---- terrain-analysis ----

@spatial.command(name="terrain")
@click.option("--dem", "-d", type=click.Path(exists=True), required=True, help="DEM raster path")
@click.option("--vector", "-v", type=click.Path(exists=True), required=True, help="Region boundary SHP")
@click.option("--output", "-o", type=click.Path(), required=True, help="Output CSV path")
@click.option("--id-field", default="region_id", help="ID field in vector")
def _terrain(dem, vector, output, id_field):
    """Compute terrain metrics from DEM: slope, aspect, relief, TPI."""
    engine = SpatialQueryEngine()
    out = engine.terrain_analysis(Path(dem), Path(vector), Path(output), id_field)
    click.echo(f"Terrain metrics saved: {out}")


# ---- spatial-autocorr ----

@spatial.command(name="autocorr")
@click.argument("stats_csv", type=click.Path(exists=True))
@click.option("--id-field", "-i", default="region_id", help="Region ID field")
@click.option("--value-field", "-v", default="mean", help="Value field for analysis")
@click.option("--neighbor-layer", "-n", default="cn_sheng", help="Spatial layer for adjacency")
@click.option("--output", "-o", type=click.Path(), help="Output CSV path")
def _autocorr(stats_csv, id_field, value_field, neighbor_layer, output):
    """Compute spatial autocorrelation (Moran's I) for regional data."""
    engine = SpatialQueryEngine()
    out_path = Path(output) if output else None
    result = engine.spatial_autocorr(Path(stats_csv), id_field, value_field, out_path, neighbor_layer)
    for r in result:
        click.echo(f"Moran's I = {r.get('moran_i')} (p={r.get('p_value')}) -> {r.get('pattern')}")


# ---- time-series ----

@spatial.command(name="timeseries")
@click.argument("stats_csv", type=click.Path(exists=True))
@click.option("--id-field", "-i", default="region_id", help="ID field")
@click.option("--value-field", "-v", default="mean", help="Value field")
@click.option("--time-field", "-t", default="year", help="Time field")
@click.option("--output", "-o", type=click.Path(), help="Output CSV path")
def _timeseries(stats_csv, id_field, value_field, time_field, output):
    """Analyze time series trends and seasonality."""
    engine = SpatialQueryEngine()
    out_path = Path(output) if output else None
    results = engine.time_series_analysis(Path(stats_csv), id_field, value_field, time_field, out_path)
    for r in results:
        click.echo(f"{r.get(id_field, '?')}: {r.get('trend')} trend, "
                   f"rate={r.get('rate_per_year')}/yr, {r.get('seasonality')}")


# ---- to-corpus ----

@spatial.command(name="to-corpus")
@click.argument("layer_id", type=str)
@click.option("--project", "-p", "project_path", type=click.Path(), default=".",
              help="Target project directory")
@click.option("--id-prefix", default="SPATIAL", help="Prefix for corpus IDs")
def _to_corpus(layer_id, project_path, id_prefix):
    """Convert a spatial layer's attribute table to corpus units."""
    from pathlib import Path
    engine = SpatialQueryEngine()
    proj = Path(project_path).resolve()
    try:
        units, evidence = engine.layer_to_corpus(layer_id, proj, id_prefix)
        click.echo(f"Generated: {units} corpus units, {evidence} evidence links from '{layer_id}'")
    except Exception as e:
        click.echo(str(e), err=True)
        raise SystemExit(1)


# ---- batch-zonal-stats ----

@spatial.command(name="batch-zonal-stats")
@click.argument("raster_dir", type=click.Path(exists=True))
@click.option("--vector", "-v", type=click.Path(exists=True), required=True,
              help="Boundary SHP file")
@click.option("--output-dir", "-o", type=click.Path(), required=True,
              help="Output directory for CSV files")
@click.option("--id-field", default="glacier_id", help="ID field in vector")
@click.option("--stats", default="mean,median,std,min,max,count",
              help="Comma-separated statistics")
@click.option("--pattern", default="*.tif,*.nc", help="Glob pattern(s) for raster files, comma-separated")
@click.option("--nodata", type=float, default=None, help="Nodata override")
def _batch_zonal_stats(raster_dir, vector, output_dir, id_field, stats, pattern, nodata):
    """Process all TIFF/NC files in a directory against one boundary SHP.

    Each raster produces one CSV with zonal statistics.
    Useful for multi-year or multi-variable batch processing.

    \b
    Example:
        geocorpus spatial batch-zonal-stats D:/data/rasters/ \\
            --vector glacier_boundary.shp -o D:/data/stats/
    """
    stats_list = [s.strip() for s in stats.split(",")]
    engine = SpatialQueryEngine()
    try:
        engine.batch_zonal_stats(
            Path(raster_dir), Path(vector), Path(output_dir),
            id_field, stats_list, nodata, pattern)
    except ImportError as e:
        click.echo(str(e), err=True)
        raise SystemExit(1)
