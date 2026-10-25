"""LayerRegistry -- manage spatial data layers and their metadata.

Fixed grid system (ChinaGeoLink):
    30m / 90m / 250m / 1km / 5km / 10km pixel resolutions.
    Each raster is registered against one of these standard grid levels.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

# Standard fixed grid levels (ChinaGeoLink)
STANDARD_GRID_LEVELS = {
    "30m":  {"resolution_m": 30,   "grid_cell_deg": 0.0002778, "description": "精细尺度 (冰川表面细节)"},
    "90m":  {"resolution_m": 90,   "grid_cell_deg": 0.0008333, "description": "高分辨率 (山地区域)"},
    "250m": {"resolution_m": 250,  "grid_cell_deg": 0.00225,   "description": "中等分辨率 (区域尺度)"},
    "1km":  {"resolution_m": 1000, "grid_cell_deg": 0.008993,  "description": "公里级 (全国气候)"},
    "5km":  {"resolution_m": 5000, "grid_cell_deg": 0.045,     "description": "粗分辨率 (流域/气候带)"},
    "10km": {"resolution_m": 10000,"grid_cell_deg": 0.09,      "description": "大尺度 (全球模式)"},
}

SPATIAL_SCALES = ["grid_30m", "grid_90m", "grid_250m", "grid_1km", "grid_5km", "grid_10km",
                  "object", "region", "national", "multi_scale"]


def detect_grid_level(bounds: tuple[float, float, float, float],
                      width: int, height: int) -> str | None:
    """Auto-detect the closest standard grid level from raster dimensions."""
    if width == 0 or height == 0:
        return None
    deg_per_pixel = (bounds[2] - bounds[0]) / width
    for name, info in STANDARD_GRID_LEVELS.items():
        ratio = deg_per_pixel / info["grid_cell_deg"]
        if 0.7 < ratio < 1.5:
            return name
    return None


@dataclass
class LayerMeta:
    """Metadata for a spatial data layer."""

    layer_id: str
    layer_name: str
    layer_type: str  # admin_boundary, river_basin, climate_zone, terrain, custom
    geometry_type: str  # polygon, point, line, multipolygon
    crs: str = "EPSG:4326"
    name_field: str = "name_zh"
    id_field: str = "adcode"
    fields: list[str] = field(default_factory=list)
    feature_count: int = 0
    source: str = ""
    imported_at: str = ""
    notes: str = ""

    def to_dict(self) -> dict:
        return {
            "layer_id": self.layer_id,
            "layer_name": self.layer_name,
            "layer_type": self.layer_type,
            "geometry_type": self.geometry_type,
            "crs": self.crs,
            "name_field": self.name_field,
            "id_field": self.id_field,
            "fields": self.fields,
            "feature_count": self.feature_count,
            "source": self.source,
            "imported_at": self.imported_at,
            "notes": self.notes,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "LayerMeta":
        return cls(**{k: v for k, v in d.items() if k in cls.__dataclass_fields__})


class LayerRegistry:
    """Discovers, loads, and manages spatial data layers stored as GeoParquet."""

    def __init__(self, data_dir: Optional[Path] = None):
        if data_dir is None:
            self.data_dir = Path(__file__).parent / "data"
        else:
            self.data_dir = Path(data_dir)

    def list_layers(self) -> list[LayerMeta]:
        """List all registered spatial layers with their metadata."""
        layers = []
        for meta_path in sorted(self.data_dir.glob("*.meta.json")):
            try:
                meta = LayerMeta.from_dict(json.loads(meta_path.read_text(encoding="utf-8")))
                layers.append(meta)
            except Exception:
                continue
        return layers

    def get_layer(self, layer_id: str) -> Optional[LayerMeta]:
        """Get metadata for a specific layer."""
        meta_path = self.data_dir / f"{layer_id}.meta.json"
        if meta_path.exists():
            return LayerMeta.from_dict(json.loads(meta_path.read_text(encoding="utf-8")))
        return None

    def get_data_path(self, layer_id: str) -> Optional[Path]:
        """Get the GeoParquet file path for a layer."""
        path = self.data_dir / f"{layer_id}.geoparquet"
        if path.exists():
            return path
        return None

    def register(self, meta: LayerMeta) -> None:
        """Write layer metadata to the data directory."""
        meta_path = self.data_dir / f"{meta.layer_id}.meta.json"
        meta_path.write_text(
            json.dumps(meta.to_dict(), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    def unregister(self, layer_id: str) -> bool:
        """Remove a layer's metadata and data files."""
        meta_path = self.data_dir / f"{layer_id}.meta.json"
        data_path = self.data_dir / f"{layer_id}.geoparquet"
        removed = False
        for p in [meta_path, data_path]:
            if p.exists():
                p.unlink()
                removed = True
        return removed

    # ── Raster layer support ──

    def list_rasters(self) -> list[dict]:
        """List all registered raster layers."""
        rasters = []
        for p in sorted(self.data_dir.glob("*.raster.json")):
            try:
                rasters.append(json.loads(p.read_text(encoding="utf-8")))
            except Exception:
                continue
        return rasters

    def get_raster_meta(self, raster_id: str) -> dict | None:
        """Get metadata for a raster layer."""
        p = self.data_dir / f"{raster_id}.raster.json"
        if p.exists():
            return json.loads(p.read_text(encoding="utf-8"))
        return None

    def get_raster_path(self, raster_id: str) -> Path | None:
        """Get the raster file path. Returns None if not found."""
        meta = self.get_raster_meta(raster_id)
        if meta:
            fname = meta.get("filename", f"{raster_id}.tif")
            p = self.data_dir / fname
            if p.exists():
                return p
        return None

    def register_raster(self, raster_id: str, source_path: Path,
                         meta: dict | None = None,
                         grid_level: str | None = None,
                         target_crs: str = "EPSG:4326",
                         reproject: bool = False) -> Path:
        """Copy a raster file into the data directory and register metadata.

        Args:
            raster_id: Unique raster layer ID.
            source_path: Path to the source TIFF/NC file.
            meta: Optional metadata dict (variable, time_range, spatial_scale, etc.).
            grid_level: Fixed grid level (30m/90m/250m/1km/5km/10km). Auto-detected.
            target_crs: Target CRS for standardization (default EPSG:4326).
            reproject: If True, reproject to target_crs during import.

        Returns:
            Path to the copied/reprojected raster file in the data directory.
        """
        suffix = source_path.suffix.lower()
        dest_name = f"{raster_id}{suffix}"
        dest = self.data_dir / dest_name
        shutil = __import__("shutil")

        source_crs = None
        raster_bounds = None
        raster_shape = None

        # Read raster metadata
        try:
            import rasterio
            from rasterio.warp import calculate_default_transform, reproject as rp, Resampling
            with rasterio.open(source_path) as src:
                source_crs = str(src.crs) if src.crs else None
                raster_shape = (src.width, src.height)

                if reproject and source_crs and source_crs != target_crs:
                    # Compute target transform and dimensions
                    transform, width, height = calculate_default_transform(
                        src.crs, target_crs, src.width, src.height,
                        *src.bounds)
                    kwargs = src.meta.copy()
                    kwargs.update({
                        "crs": target_crs, "transform": transform,
                        "width": width, "height": height,
                    })
                    with rasterio.open(dest, "w", **kwargs) as dst:
                        for i in range(1, src.count + 1):
                            rp(source=src.read(i), destination=__import__("numpy").zeros(
                                (height, width), dtype=src.dtypes[i-1]),
                               src_transform=src.transform, src_crs=src.crs,
                               dst_transform=transform, dst_crs=target_crs,
                               resampling=Resampling.bilinear)
                    raster_bounds = (transform * (0, 0), transform * (width, height))
                    raster_bounds = (*raster_bounds[0], *raster_bounds[1])
                    raster_shape = (width, height)
                else:
                    shutil.copy2(source_path, dest)
                    raster_bounds = src.bounds
        except ImportError:
            shutil.copy2(source_path, dest)
        except Exception:
            # Try xarray for NetCDF files
            if suffix in (".nc", ".nc4"):
                try:
                    import xarray as xr
                    ds = xr.open_dataset(str(source_path))
                    # Extract spatial dims
                    for dim in ds.dims:
                        lower = dim.lower()
                        if lower in ("lat", "latitude"):
                            lat_vals = ds.coords[dim].values.astype(float)
                        elif lower in ("lon", "longitude"):
                            lon_vals = ds.coords[dim].values.astype(float)
                    raster_bounds = (float(lon_vals.min()), float(lat_vals.min()),
                                     float(lon_vals.max()), float(lat_vals.max()))
                    raster_shape = (len(lon_vals), len(lat_vals))
                    source_crs = "EPSG:4326"
                    ds.close()
                except Exception:
                    pass
            shutil.copy2(source_path, dest)

        # Auto-detect grid level from bounds + shape
        detected_grid = grid_level
        if detected_grid is None and raster_bounds and raster_shape:
            try:
                bounds_tuple = (raster_bounds.left, raster_bounds.bottom,
                                raster_bounds.right, raster_bounds.top)
            except AttributeError:
                bounds_tuple = tuple(raster_bounds)
            detected_grid = detect_grid_level(bounds_tuple, raster_shape[0], raster_shape[1])

        spatial_scale_from_grid = f"grid_{detected_grid}" if detected_grid else "grid"

        meta_dict = (meta or {}) | {
            "raster_id": raster_id,
            "layer_type": "raster",
            "filename": dest_name,
            "format": suffix.lstrip("."),
            "size_bytes": dest.stat().st_size,
            "source": str(source_path),
            "source_crs": source_crs,
            "target_crs": target_crs,
            "reprojected": reproject and source_crs != target_crs,
            "imported_at": __import__("datetime").datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "grid_level": detected_grid,
            "spatial_scale": meta.get("spatial_scale", spatial_scale_from_grid) if meta else spatial_scale_from_grid,
        }
        if raster_bounds:
            try:
                meta_dict["bounds"] = [round(x, 6) for x in raster_bounds]
            except TypeError:
                meta_dict["bounds"] = [round(x, 6) for x in raster_bounds]
        if raster_shape:
            meta_dict["shape"] = list(raster_shape)

        (self.data_dir / f"{raster_id}.raster.json").write_text(
            json.dumps(meta_dict, ensure_ascii=False, indent=2), encoding="utf-8")
        return dest

    def unregister_raster(self, raster_id: str) -> bool:
        """Remove a raster and its metadata."""
        removed = False
        for p in [self.data_dir / f"{raster_id}.raster.json"]:
            if p.exists():
                p.unlink()
                removed = True
        meta = self.get_raster_meta(raster_id)
        if meta:
            fname = meta.get("filename", f"{raster_id}.tif")
            fp = self.data_dir / fname
            if fp.exists():
                fp.unlink()
                removed = True
        return removed
