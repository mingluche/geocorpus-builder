"""SHP→GeoParquet import tool. Converts Shapefile to GeoParquet and registers metadata."""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

import geopandas as gpd

from .registry import LayerRegistry, LayerMeta


def import_shapefile(
    shp_path: Path,
    layer_id: str,
    layer_name: str,
    layer_type: str = "admin_boundary",
    name_field: str = "name_zh",
    id_field: str = "adcode",
    crs: str = "EPSG:4326",
    output_dir: Path | None = None,
) -> LayerMeta:
    """Convert a Shapefile to GeoParquet and register it as a spatial data layer.

    Args:
        shp_path: Path to .shp file (or directory containing .shp files).
        layer_id: Unique layer identifier (e.g. "cn_provinces").
        layer_name: Human-readable layer name (e.g. "中国省级行政区划").
        layer_type: Type of boundary data.
        name_field: Field containing the region name.
        id_field: Field containing the unique region ID.
        crs: Target coordinate reference system.
        output_dir: Where to write the .geoparquet and .meta.json files.
                    Defaults to the package spatial data directory.

    Returns:
        LayerMeta describing the imported layer.
    """
    shp_path = Path(shp_path).resolve()
    if not shp_path.exists():
        raise FileNotFoundError(f"Shapefile not found: {shp_path}")

    if output_dir is None:
        output_dir = Path(__file__).parent / "data"
    output_dir = Path(output_dir).resolve()
    output_dir.mkdir(parents=True, exist_ok=True)

    # Read SHP
    print(f"Reading shapefile: {shp_path}")
    gdf = gpd.read_file(str(shp_path))

    if gdf.crs is None:
        gdf = gdf.set_crs(crs)
    elif gdf.crs.to_string() != crs:
        gdf = gdf.to_crs(crs)

    # Detect fields
    fields = [c for c in gdf.columns if c != "geometry"]
    geometry_type = gdf.geometry.geom_type.iloc[0] if len(gdf) > 0 else "unknown"

    # Validate name_field and id_field
    if name_field not in gdf.columns:
        available = [c for c in fields if "name" in c.lower() or "名" in c]
        if available:
            name_field = available[0]
            print(f"  Auto-detected name field: '{name_field}'")
        else:
            name_field = fields[0] if fields else "FID"
            print(f"  Using first field as name: '{name_field}'")

    if id_field not in gdf.columns:
        available = [c for c in fields if "code" in c.lower() or "id" in c.lower() or "码" in c]
        if available:
            id_field = available[0]
            print(f"  Auto-detected ID field: '{id_field}'")
        else:
            id_field = fields[0] if fields else "FID"
            print(f"  Using first field as ID: '{id_field}'")

    # Write GeoParquet
    geoparquet_path = output_dir / f"{layer_id}.geoparquet"
    print(f"Writing GeoParquet: {geoparquet_path}")
    gdf.to_parquet(geoparquet_path)
    file_size_mb = geoparquet_path.stat().st_size / (1024 * 1024)

    # Build metadata
    meta = LayerMeta(
        layer_id=layer_id,
        layer_name=layer_name,
        layer_type=layer_type,
        geometry_type=geometry_type,
        crs=crs,
        name_field=name_field,
        id_field=id_field,
        fields=fields,
        feature_count=len(gdf),
        source=str(shp_path.name),
        imported_at=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    )

    # Register
    registry = LayerRegistry(output_dir)
    registry.register(meta)

    print(f"Imported '{layer_name}': {meta.feature_count} features, "
          f"{file_size_mb:.1f} MB, {len(fields)} fields")
    return meta


def import_directory(
    directory: Path,
    output_dir: Path | None = None,
    file_map: dict[str, dict] | None = None,
) -> list[LayerMeta]:
    """Import all .shp files in a directory.

    Args:
        directory: Directory containing .shp files.
        output_dir: Output directory for GeoParquet files.
        file_map: Optional dict mapping filename stems to import params.
                  e.g. {"cn_provinces": {"layer_name": "省级行政区", "layer_type": "admin_boundary"}}

    Returns:
        List of LayerMeta for all imported layers.
    """
    directory = Path(directory)
    results: list[LayerMeta] = []

    shp_files = list(directory.glob("*.shp"))
    if not shp_files:
        raise FileNotFoundError(f"No .shp files found in {directory}")

    for shp_path in shp_files:
        stem = shp_path.stem
        params = (file_map or {}).get(stem, {})

        meta = import_shapefile(
            shp_path=shp_path,
            layer_id=params.get("layer_id", stem),
            layer_name=params.get("layer_name", stem),
            layer_type=params.get("layer_type", "custom"),
            name_field=params.get("name_field", "name_zh"),
            id_field=params.get("id_field", "adcode"),
            crs=params.get("crs", "EPSG:4326"),
            output_dir=output_dir,
        )
        results.append(meta)

    return results
