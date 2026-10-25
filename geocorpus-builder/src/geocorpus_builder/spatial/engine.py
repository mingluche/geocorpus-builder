"""SpatialQueryEngine -- full spatial relationship queries on bundled GeoParquet layers."""

from __future__ import annotations

import tempfile
from pathlib import Path
from typing import Optional

import geopandas as gpd
import pandas as pd
from shapely.geometry import Point, shape
from shapely.ops import transform
from shapely import wkt

from .registry import LayerRegistry, LayerMeta


class SpatialQueryEngine:
    """Query engine for spatial operations across bundled GeoParquet layers.

    Supports: point location, neighbor lookup, geometric overlap,
    distance calculation, and nearby search.
    """

    def __init__(self, data_dir: Optional[Path] = None):
        self.registry = LayerRegistry(data_dir)
        self._cache: dict[str, gpd.GeoDataFrame] = {}

    def list_layers(self) -> list[LayerMeta]:
        return self.registry.list_layers()

    # ----- Point location -----

    def locate(self, lon: float, lat: float,
               layers: Optional[list[str]] = None) -> dict[str, dict]:
        """Find which regions contain the given point on each layer.

        Returns: {layer_id: {field: value, ...}} for each matching layer.
        """
        point = Point(lon, lat)
        results: dict[str, dict] = {}

        target_layers = layers or [m.layer_id for m in self.list_layers()]

        for layer_id in target_layers:
            gdf = self._load_layer(layer_id)
            if gdf is None:
                continue
            meta = self.registry.get_layer(layer_id)
            if meta is None:
                continue

            mask = gdf.contains(point)
            matches = gdf[mask]
            for _, row in matches.iterrows():
                info = {col: str(row[col]) for col in meta.fields if col in row.index}
                info["layer_id"] = layer_id
                info["layer_name"] = meta.layer_name
                results[layer_id] = info
                break  # Take first match

        return results

    def locate_batch(self, points: list[tuple[float, float]],
                     layers: Optional[list[str]] = None) -> list[dict[str, dict]]:
        """Batch locate: return region info for each point."""
        return [self.locate(lon, lat, layers) for lon, lat in points]

    # ----- Neighbors -----

    def neighbors(self, region_id: str, layer: str) -> list[dict]:
        """Find neighboring regions that share a boundary with the given region."""
        meta = self.registry.get_layer(layer)
        gdf = self._load_layer(layer)
        if gdf is None or meta is None:
            return []

        id_field = meta.id_field
        target = gdf[gdf[id_field].astype(str) == str(region_id)]
        if target.empty:
            return []

        target_geom = target.geometry.iloc[0]
        neighbor_list: list[dict] = []

        for _, row in gdf.iterrows():
            if str(row[id_field]) == str(region_id):
                continue
            if target_geom.touches(row.geometry) or target_geom.intersects(row.geometry):
                entry = {col: str(row[col]) for col in meta.fields if col in row.index}
                entry["layer_id"] = layer
                neighbor_list.append(entry)

        return neighbor_list

    # ----- Overlap -----

    def overlap(self, geometry, layer: str) -> list[dict]:
        """Calculate overlap between a geometry and regions in a layer.

        geometry: WKT string, GeoJSON dict, or shapely geometry.
        Returns: list of {region fields, overlap_area_m2, area_fraction}.
        """
        meta = self.registry.get_layer(layer)
        gdf = self._load_layer(layer)
        if gdf is None or meta is None:
            return []

        geom = self._normalize_geometry(geometry)
        results: list[dict] = []

        for _, row in gdf.iterrows():
            region_geom = row.geometry
            if not geom.intersects(region_geom):
                continue
            intersection = geom.intersection(region_geom)
            if intersection.is_empty:
                continue

            frac = intersection.area / geom.area if geom.area > 0 else 0
            entry = {col: str(row[col]) for col in meta.fields if col in row.index}
            entry["layer_id"] = layer
            entry["overlap_area_m2"] = round(intersection.area, 2)
            entry["area_fraction"] = round(frac, 6)
            results.append(entry)

        results.sort(key=lambda x: x["area_fraction"], reverse=True)
        return results

    # ----- Distance -----

    def distance(self, geom_a, geom_b) -> float:
        """Calculate distance in meters between two geometries (assumes EPSG:4326 input).

        Returns approximate distance in meters using a simple scaling.
        For precise results, geometries should be projected first.
        """
        ga = self._normalize_geometry(geom_a)
        gb = self._normalize_geometry(geom_b)
        return ga.distance(gb) * 111320.0  # rough meters per degree at equator

    # ----- Nearby -----

    def find_nearby(self, geometry, layer: str,
                    max_distance_m: float = 100000.0) -> list[dict]:
        """Find regions within a max distance of the given geometry."""
        meta = self.registry.get_layer(layer)
        gdf = self._load_layer(layer)
        if gdf is None or meta is None:
            return []

        geom = self._normalize_geometry(geometry)
        buffer_deg = max_distance_m / 111320.0
        search_area = geom.buffer(buffer_deg)
        results: list[dict] = []

        for _, row in gdf.iterrows():
            region_geom = row.geometry
            if not search_area.intersects(region_geom):
                continue
            dist_deg = geom.distance(region_geom)
            dist_m = dist_deg * 111320.0
            entry = {col: str(row[col]) for col in meta.fields if col in row.index}
            entry["layer_id"] = layer
            entry["distance_m"] = round(dist_m, 1)
            results.append(entry)

        results.sort(key=lambda x: x["distance_m"])
        return results

    # ----- Raster zonal statistics -----

    @staticmethod
    def _open_raster(raster_path: Path, variable: str | None = None):
        """Open a raster file (GeoTIFF or NetCDF) as a rasterio dataset.

        For NetCDF files, extracts the 2D data variable and wraps it in a
        temporary in-memory GeoTIFF that rasterio can process.

        Returns:
            (rasterio dataset, Path to temp file or original file)
            Caller should close the dataset after use.
        """
        import rasterio

        suffix = raster_path.suffix.lower()
        if suffix not in (".nc", ".nc4"):
            return rasterio.open(str(raster_path)), raster_path

        # NetCDF: read with xarray, convert to in-memory GeoTIFF
        try:
            import xarray as xr
            import numpy as np
        except ImportError:
            raise ImportError(
                "xarray + netcdf4 required for NetCDF files. "
                "Install: pip install xarray netcdf4 h5netcdf"
            )

        ds = xr.open_dataset(str(raster_path))

        # Pick the data variable
        if variable and variable in ds:
            data_var = variable
        else:
            data_vars = [v for v in ds.data_vars if v not in ds.coords]
            if not data_vars:
                raise ValueError(f"No data variables found in {raster_path}")
            data_var = data_vars[0]

        da = ds[data_var]

        # Get 2D slice: drop non-spatial dims (time, band, etc.)
        spatial_dims = ["lat", "latitude", "y", "lon", "longitude", "x"]
        for dim in da.dims:
            if dim.lower() not in spatial_dims:
                da = da.isel({dim: 0})

        # Ensure we have 2D
        if da.ndim > 2:
            da = da.isel({d: 0 for d in da.dims if d.lower() not in spatial_dims})
        if da.ndim != 2:
            raise ValueError(f"Cannot reduce {data_var} to 2D raster (got {da.ndim}D)")

        arr = da.values.astype(np.float32)
        arr = np.nan_to_num(arr, nan=np.nan)

        # Detect CRS
        crs = "EPSG:4326"
        if hasattr(da, "rio") and da.rio.crs:
            crs = str(da.rio.crs)

        # Compute geotransform from coordinate arrays
        lat_coords = None
        lon_coords = None
        for dim_name in da.dims:
            lower = dim_name.lower()
            coord = da.coords[dim_name].values.astype(float)
            if lower in ("lat", "latitude", "y"):
                lat_coords = coord
            elif lower in ("lon", "longitude", "x"):
                lon_coords = coord

        if lat_coords is None or lon_coords is None:
            raise ValueError(
                f"Cannot determine lat/lon coordinates from dims: {list(da.dims)}"
            )

        nx = len(lon_coords)
        ny = len(lat_coords)
        dx = (lon_coords[-1] - lon_coords[0]) / max(nx - 1, 1)
        dy = (lat_coords[-1] - lat_coords[0]) / max(ny - 1, 1)
        from rasterio.transform import from_bounds
        transform = from_bounds(
            float(lon_coords.min()), float(lat_coords.min()),
            float(lon_coords.max()), float(lat_coords.max()),
            nx, ny,
        )

        ds.close()

        # Write to temp GeoTIFF and open
        tmp = tempfile.NamedTemporaryFile(suffix=".tif", delete=False)
        tmp_path = Path(tmp.name)
        with rasterio.open(
            str(tmp_path), "w", driver="GTiff",
            height=ny, width=nx, count=1, dtype="float32",
            crs=crs, transform=transform, nodata=np.nan,
        ) as dst:
            dst.write(arr, 1)

        dataset = rasterio.open(str(tmp_path))
        return dataset, tmp_path

    def zonal_stats(self,
                    raster_path: Path,
                    vector_path: Path,
                    output_path: Path,
                    id_field: str = "glacier_id",
                    stats_list: list[str] | None = None,
                    nodata: float | None = None) -> Path:
        """Compute zonal statistics: raster values within vector polygons.

        Args:
            raster_path: Path to GeoTIFF raster file.
            vector_path: Path to vector file (SHP, GeoJSON, etc.) with polygon boundaries.
            output_path: Path for output CSV.
            id_field: Field in vector that uniquely identifies each polygon.
            stats_list: Statistics to compute. Default: ['mean', 'median', 'std', 'min', 'max', 'count'].
            nodata: Raster nodata value to mask out. Auto-detected if None.

        Returns:
            Path to the output CSV file.
        """
        try:
            import rasterio
            import rasterio.mask
        except ImportError:
            raise ImportError(
                "rasterio is required for zonal statistics. "
                "Install it with: pip install rasterio\n"
                "Or: pip install geocorpus-builder[spatial]"
            )

        if stats_list is None:
            stats_list = ["mean", "median", "std", "min", "max", "count"]

        gdf = gpd.read_file(str(vector_path))
        if id_field not in gdf.columns:
            available = [c for c in gdf.columns if c != "geometry"]
            raise ValueError(
                f"ID field '{id_field}' not found in vector. Available fields: {available}"
            )

        results: list[dict] = []

        src, tmp_path = self._open_raster(raster_path)
        try:
            if nodata is None:
                nodata = src.nodata
            if gdf.crs != src.crs:
                gdf = gdf.to_crs(src.crs)

            for _, row in gdf.iterrows():
                geom = row.geometry
                obj_id = row[id_field]
                entry = {id_field: obj_id}

                # Get the raster window for this geometry
                try:
                    geom_json = [geom.__geo_interface__]
                    out_image, out_transform = rasterio.mask.mask(
                        src, geom_json, crop=True, nodata=nodata
                    )
                    data = out_image[0]  # first band
                    valid = data[data != nodata] if nodata is not None else data.flatten()
                    valid = valid[~pd.isna(valid)]
                except Exception:
                    # No valid data or geometry out of bounds
                    for s in stats_list:
                        entry[s] = None
                    results.append(entry)
                    continue

                if len(valid) == 0:
                    for s in stats_list:
                        entry[s] = None
                else:
                    for s in stats_list:
                        if s == "mean":
                            entry[s] = round(float(valid.mean()), 4)
                        elif s == "median":
                            entry[s] = round(float(pd.Series(valid).median()), 4)
                        elif s == "std":
                            entry[s] = round(float(valid.std()), 4)
                        elif s == "min":
                            entry[s] = round(float(valid.min()), 4)
                        elif s == "max":
                            entry[s] = round(float(valid.max()), 4)
                        elif s == "count":
                            entry[s] = int(len(valid))
                        elif s == "sum":
                            entry[s] = round(float(valid.sum()), 4)

                # Also capture centroid for spatial enrichment
                centroid = geom.centroid
                entry["lon"] = round(centroid.x, 6)
                entry["lat"] = round(centroid.y, 6)
                entry["variable"] = Path(raster_path).stem

                results.append(entry)

            # Write CSV
            result_df = pd.DataFrame(results)
            output_path.parent.mkdir(parents=True, exist_ok=True)
            result_df.to_csv(output_path, index=False, encoding="utf-8")

            print(f"Zonal stats: {len(results)} polygons, {len(stats_list)} statistics "
                  f"({result_df[id_field].nunique()} unique {id_field}s)")
            return output_path
        finally:
            src.close()
            if tmp_path != raster_path and tmp_path.exists():
                tmp_path.unlink()

    # ----- Map display -----

    def show(self, layers: list[str], output_path: Path,
             title: str = "", point: tuple[float, float] | None = None,
             dpi: int = 150) -> Path:
        """Render spatial layers as a map PNG.

        Args:
            layers: List of layer IDs to display, in draw order.
            output_path: PNG output file path.
            title: Optional map title.
            point: Optional (lon, lat) to mark on the map.
            dpi: Output resolution.

        Returns:
            Path to the saved PNG.
        """
        try:
            import matplotlib
            matplotlib.use('Agg')
            import matplotlib.pyplot as plt
            import matplotlib.font_manager as fm
        except ImportError:
            raise ImportError("matplotlib is required. Install: pip install matplotlib")

        # Detect a CJK-capable font for Chinese labels
        _cjk_fonts = [f.name for f in fm.fontManager.ttflist
                      if any(k in f.name for k in ('SimHei', 'Microsoft YaHei',
                                                    'Noto Sans SC', 'Noto Sans CJK'))]
        if _cjk_fonts:
            plt.rcParams['font.sans-serif'] = [_cjk_fonts[0], 'DejaVu Sans']
        plt.rcParams['axes.unicode_minus'] = False

        fig, ax = plt.subplots(1, 1, figsize=(12, 10))
        cmaps = ['tab20', 'Set3', 'Pastel1', 'tab20b', 'tab20c']
        idx = 0

        for layer_id in layers:
            gdf = self._load_layer(layer_id)
            meta = self.registry.get_layer(layer_id)
            if gdf is None:
                continue

            name_col = meta.name_field if meta and meta.name_field in gdf.columns else None
            n_features = len(gdf)

            if name_col:
                # Convert to categorical string to avoid geopandas colorbar/legend confusion
                gdf[name_col] = gdf[name_col].astype(str)
                gdf.plot(ax=ax, column=name_col, legend=True, cmap=cmaps[idx % len(cmaps)],
                        edgecolor='black', linewidth=0.5, alpha=0.6)
            else:
                gdf.boundary.plot(ax=ax, color='black', linewidth=0.4, alpha=0.5)
                gdf.plot(ax=ax, facecolor=cmaps[idx % len(cmaps)], alpha=0.3, edgecolor='none')

            idx += 1

        if point:
            ax.scatter(point[0], point[1], c='red', s=80, marker='*', zorder=10, edgecolors='black')
            ax.annotate(f'  ({point[0]:.2f}, {point[1]:.2f})',
                       (point[0], point[1]), fontsize=9, color='red')

        ax.set_title(title or ' + '.join(layers), fontsize=14)
        ax.set_xlabel('Longitude')
        ax.set_ylabel('Latitude')
        plt.tight_layout()
        output_path.parent.mkdir(parents=True, exist_ok=True)
        plt.savefig(str(output_path), dpi=dpi)
        plt.close()
        return output_path

    # ----- Terrain analysis (from DEM raster) -----

    def terrain_analysis(self, dem_path: Path, vector_path: Path,
                          output_path: Path, id_field: str = "region_id") -> Path:
        """Compute terrain metrics from DEM: slope, aspect, relief, TRI.

        Requires rasterio. Outputs a CSV with slope_mean, slope_max,
        aspect_dominant, relief, and terrain ruggedness index.
        """
        try:
            import rasterio
            import rasterio.mask
            import numpy as np
        except ImportError:
            raise ImportError("rasterio + numpy required: pip install rasterio numpy")

        gdf = gpd.read_file(str(vector_path))
        results = []

        src, tmp_path = self._open_raster(dem_path)
        try:
            if gdf.crs != src.crs:
                gdf = gdf.to_crs(src.crs)
            dem = src.read(1).astype(float)
            nodata = src.nodata
            if nodata is not None:
                dem[dem == nodata] = np.nan
            transform = src.transform
            dx = transform[0]
            dy = -transform[4]

            for _, row in gdf.iterrows():
                geom = row.geometry
                rid = row[id_field]
                centroid = geom.centroid
                entry = {id_field: rid, "lon": round(centroid.x, 6), "lat": round(centroid.y, 6)}

                try:
                    geom_json = [geom.__geo_interface__]
                    out_img, out_tf = rasterio.mask.mask(src, geom_json, crop=True, nodata=nodata)
                    patch = out_img[0].astype(float)
                    if nodata is not None:
                        patch[patch == nodata] = np.nan
                    valid = patch[~np.isnan(patch)]
                except Exception:
                    for k in ["slope_mean", "slope_max", "aspect_dominant", "relief", "tpi_mean"]:
                        entry[k] = None
                    results.append(entry)
                    continue

                if len(valid) < 4:
                    continue

                # Slope
                gy, gx = np.gradient(patch, dy, dx)
                slope = np.arctan(np.sqrt(gx**2 + gy**2)) * 180 / np.pi
                # Aspect
                aspect = np.arctan2(-gx, gy) * 180 / np.pi
                aspect[aspect < 0] += 360
                aspect_labels = {0: "北", 45: "东北", 90: "东", 135: "东南",
                                 180: "南", 225: "西南", 270: "西", 315: "西北", 360: "北"}
                valid_aspect = aspect[~np.isnan(aspect)]
                if len(valid_aspect) > 0:
                    mean_asp = np.mean(valid_aspect)
                    asp_key = min(aspect_labels.keys(), key=lambda k: abs(k - mean_asp))
                    dom_aspect = aspect_labels[asp_key]
                else:
                    dom_aspect = "?"

                entry["slope_mean"] = round(float(np.nanmean(slope)), 2)
                entry["slope_max"] = round(float(np.nanmax(slope)), 2)
                entry["aspect_dominant"] = dom_aspect
                entry["relief"] = round(float(np.nanmax(valid) - np.nanmin(valid)), 2)

                # Terrain Position Index (TPI): cell minus neighborhood mean
                radius = min(5, patch.shape[0] // 4, patch.shape[1] // 4)
                if radius >= 1:
                    from scipy.ndimage import uniform_filter
                    neighborhood = uniform_filter(patch, size=radius * 2 + 1)
                    tpi = patch - neighborhood
                    entry["tpi_mean"] = round(float(np.nanmean(tpi)), 2)

                results.append(entry)

            import pandas as pd
            result_df = pd.DataFrame(results)
            output_path.parent.mkdir(parents=True, exist_ok=True)
            result_df.to_csv(output_path, index=False, encoding="utf-8")
            return output_path
        finally:
            src.close()
            if tmp_path != dem_path and tmp_path.exists():
                tmp_path.unlink()

    # ----- Spatial autocorrelation (Moran's I) -----

    def spatial_autocorr(self, stats_csv: Path, id_field: str, value_field: str,
                          output_path: Path | None = None,
                          neighbor_layer: str = "cn_sheng") -> list[dict]:
        """Compute spatial autocorrelation (Moran's I) for a set of regions.

        Uses adjacency from a spatial layer to define weights.
        Returns list of result dicts with moran_i, p_value, pattern, etc.
        """
        import pandas as pd
        import numpy as np

        df = pd.read_csv(stats_csv)
        if id_field not in df.columns or value_field not in df.columns:
            raise ValueError(f"Fields {id_field}/{value_field} not found in {stats_csv}")

        # Build adjacency weight matrix from spatial layer
        gdf = self._load_layer(neighbor_layer)
        if gdf is None:
            raise ValueError(f"Layer {neighbor_layer} not found")

        meta = self.registry.get_layer(neighbor_layer)
        nid_field = meta.id_field if meta else "gb"
        if nid_field not in gdf.columns:
            nid_field = gdf.columns[0]

        ids = df[id_field].astype(str).tolist()
        n = len(ids)
        if n < 3:
            return [{"error": "Need at least 3 regions"}]

        # Build weight matrix from adjacency
        W = np.zeros((n, n))
        id_to_idx = {rid: i for i, rid in enumerate(ids)}
        for i, rid in enumerate(ids):
            neighbors = self.neighbors(rid, neighbor_layer)
            for nb in neighbors:
                nb_id = nb.get(nid_field, "")
                if nb_id in id_to_idx:
                    j = id_to_idx[nb_id]
                    W[i, j] = 1
                    W[j, i] = 1

        # Row-standardize
        row_sums = W.sum(axis=1)
        row_sums[row_sums == 0] = 1
        W = W / row_sums[:, np.newaxis]

        # Moran's I computation
        values = df[value_field].values.astype(float)
        z = values - values.mean()
        z_std = z / values.std()

        I = (W * np.outer(z_std, z_std)).sum() / W.sum()
        # Approximate variance and p-value
        EI = -1.0 / (n - 1)
        # Simple randomization variance
        S1 = ((W + W.T) ** 2).sum() / 2
        S2 = (W.sum(axis=1) + W.sum(axis=0)) ** 2
        VI = (n * ((n*n - 3*n + 3)*S1 - n*S2.sum() + 3*W.sum()**2)
              - 1 * ((n*n - n)*S1 - 2*n*S2.sum() + 6*W.sum()**2))
        VI = VI / ((n - 1) * (n - 2) * (n - 3) * W.sum()**2) - EI**2
        if VI > 0:
            z_score = (I - EI) / np.sqrt(VI)
            from math import erfc
            p_value = float(np.sqrt(2/np.pi) * np.exp(-z_score**2/2) / abs(z_score)) if abs(z_score) > 0.1 else 0.5
        else:
            z_score = 0
            p_value = 1.0

        if I > 0.1:
            pattern = "集聚"
        elif I < -0.1:
            pattern = "离散"
        else:
            pattern = "随机"

        result = [{
            "id_field": id_field, "value_field": value_field,
            "n_regions": n, "moran_i": round(float(I), 4),
            "z_score": round(float(z_score), 4),
            "p_value": round(float(p_value), 4),
            "pattern": pattern,
            "neighbor_layer": neighbor_layer,
        }]

        if output_path:
            output_path.parent.mkdir(parents=True, exist_ok=True)
            pd.DataFrame(result).to_csv(output_path, index=False)

        return result

    # ----- Time series analysis -----

    def time_series_analysis(self, stats_csv: Path, id_field: str,
                               value_field: str, time_field: str = "year",
                               output_path: Path | None = None) -> list[dict]:
        """Detect trends and seasonality in time series data."""
        import pandas as pd
        import numpy as np

        df = pd.read_csv(stats_csv)
        results = []
        for rid, group in df.groupby(id_field):
            group = group.sort_values(time_field)
            times = group[time_field].values
            values = group[value_field].values.astype(float)
            if len(values) < 2:
                continue

            # Linear trend
            x = np.arange(len(values))
            slope, intercept = np.polyfit(x, values, 1)
            trend = "上升" if slope > 0 else "下降"

            # Rate per unit time
            time_span = times[-1] - times[0]
            rate = slope * len(values) / max(time_span, 1)

            # Simple seasonality detection: variance of year-over-year changes
            if len(values) >= 4:
                changes = np.diff(values)
                cv_changes = float(np.std(changes) / (abs(np.mean(changes)) + 0.01))
            else:
                cv_changes = 0

            seasonal = "有季节性波动" if cv_changes > 0.5 else "无明显季节性"

            results.append({
                id_field: str(rid), "value_field": value_field,
                "n_points": len(values), "time_range": f"{times[0]}-{times[-1]}",
                "slope": round(float(slope), 4), "rate_per_year": round(float(rate), 4),
                "trend": trend, "seasonality": seasonal,
                "start_value": round(float(values[0]), 2),
                "end_value": round(float(values[-1]), 2),
            })

        if output_path:
            output_path.parent.mkdir(parents=True, exist_ok=True)
            pd.DataFrame(results).to_csv(output_path, index=False)

        return results

    # ----- Line feature analysis -----

    def line_analysis(self, gdf, name_field: str = "name") -> list[dict]:
        """Analyze line features: length, network connectivity."""
        results = []
        for _, row in gdf.iterrows():
            geom = row.geometry
            length_m = geom.length * 111320.0  # approximate meters from degrees
            name = str(row.get(name_field, "?"))
            results.append({
                "name": name,
                "length_km": round(length_m / 1000, 2),
                "geometry_type": geom.geom_type,
            })
        return results

    # ----- Spatial layer → corpus -----

    def layer_to_corpus(self, layer_id: str, output_dir: Path,
                         id_prefix: str = "SPATIAL") -> tuple[int, int]:
        """Convert a spatial layer's attribute table into corpus units + evidence.

        Reads the GeoParquet layer, treats each row's non-geometry fields as
        data variables, and generates corpus_units.jsonl + evidence_links.jsonl.

        Args:
            layer_id: Spatial layer to convert.
            output_dir: Output directory (project root with corpus/ and evidence/).
            id_prefix: Prefix for generated corpus IDs.

        Returns:
            (corpus_units_created, evidence_links_created)
        """
        import pandas as pd
        from ..io import write_jsonl, read_jsonl

        gdf = self._load_layer(layer_id)
        meta = self.registry.get_layer(layer_id)
        if gdf is None or meta is None:
            raise ValueError(f"Layer '{layer_id}' not found")

        corpus_dir = output_dir / "corpus"
        evidence_dir = output_dir / "evidence"
        corpus_dir.mkdir(parents=True, exist_ok=True)
        evidence_dir.mkdir(parents=True, exist_ok=True)

        # Load existing data for appending
        existing_units = read_jsonl(corpus_dir / "corpus_units.jsonl") if (corpus_dir / "corpus_units.jsonl").exists() else []
        existing_evidence = read_jsonl(evidence_dir / "evidence_links.jsonl") if (evidence_dir / "evidence_links.jsonl").exists() else []
        counter = len(existing_units)

        attrs = [c for c in gdf.columns if c != "geometry"]
        id_fields = {meta.id_field, meta.name_field}
        num_fields = [c for c in attrs if c not in id_fields
                      and gdf[c].dtype in ("float64", "int64", "float32", "int32")]
        txt_fields = [c for c in attrs if c not in id_fields
                      and c not in num_fields
                      and gdf[c].dtype in ("object", "string")]
        # Process both numeric and text fields
        stat_fields = num_fields + txt_fields

        id_col = meta.id_field if meta.id_field in attrs else (attrs[0] if attrs else "FID")
        name_col = meta.name_field if meta.name_field in attrs else None

        new_units = []
        new_evidence = []
        ev_counter = len(existing_evidence)

        for _, row in gdf.iterrows():
            geo_id = str(row[id_col])
            geo_name = str(row[name_col]) if name_col and name_col in row.index else geo_id
            centroid = row.geometry.centroid

            for sf in stat_fields:
                val = row[sf]
                if pd.isna(val):
                    continue

                counter += 1
                ev_counter += 1
                cid = f"{id_prefix}_{layer_id.upper()}_{counter:04d}"
                eid = f"EV_SPATIAL_ATTR_{ev_counter:04d}"

                text = f"{meta.layer_name}{geo_name}的{sf}为{val}"
                if sf.endswith("Area") or "area" in sf.lower():
                    text += " km²"
                text += f"（来源：{layer_id}属性表）。"

                unit = {
                    "corpus_id": cid, "text": text, "text_type": "result",
                    "domain": "geospatial_data", "subdomain": layer_id,
                    "geo_object_type": meta.layer_type,
                    "geo_object_id": geo_id,
                    "spatial_scale": "region",
                    "time_range": "static",
                    "variable": sf,
                    "claim_type": "descriptive",
                    "evidence_ids": [eid],
                    "confidence": "high",
                    "source": f"spatial_layer:{layer_id}",
                    "lon": round(centroid.x, 6),
                    "lat": round(centroid.y, 6),
                }
                new_units.append(unit)

                ev = {
                    "evidence_id": eid, "corpus_id": cid,
                    "evidence_type": "vector",
                    "source_table": f"{layer_id}.geoparquet",
                    "source_id": geo_id,
                    "variable": sf, "statistic": "value",
                    "value": str(val),
                    "unit": "km²" if ("area" in sf.lower()) else "",
                    "time_range": "static",
                    "spatial_scale": "region",
                    "notes": f"来自SHP属性表: {meta.layer_name}",
                }
                new_evidence.append(ev)

        if new_units:
            write_jsonl(existing_units + new_units, corpus_dir / "corpus_units.jsonl")
            write_jsonl(existing_evidence + new_evidence, evidence_dir / "evidence_links.jsonl")

        return len(new_units), len(new_evidence)

    # ----- Batch zonal statistics -----

    def batch_zonal_stats(self,
                          raster_dir: Path,
                          vector_path: Path,
                          output_dir: Path,
                          id_field: str = "glacier_id",
                          stats_list: list[str] | None = None,
                          nodata: float | None = None,
                          pattern: str = "*.tif") -> list[Path]:
        """Process multiple TIFF/NC files in a directory against one boundary SHP.

        For each raster, generates a CSV with zonal statistics.
        Auto-detects variable name from filename stem.

        Args:
            raster_dir: Directory containing raster files.
            vector_path: Path to boundary SHP.
            output_dir: Output directory for CSV files.
            id_field: Unique ID field in vector.
            stats_list: Statistics to compute.
            nodata: Nodata value override.
            pattern: Glob pattern(s) for raster files, comma-separated.

        Returns:
            List of output CSV paths.
        """
        output_dir.mkdir(parents=True, exist_ok=True)
        results: list[Path] = []

        patterns = [p.strip() for p in pattern.split(",")]
        raster_files = []
        for pat in patterns:
            raster_files.extend(sorted(raster_dir.glob(pat)))
        raster_files = sorted(set(raster_files))
        if not raster_files:
            raise FileNotFoundError(f"No raster files matching '{pattern}' in {raster_dir}")

        print(f"Found {len(raster_files)} raster files")
        for i, rp in enumerate(raster_files, 1):
            var_name = rp.stem
            out = output_dir / f"{var_name}.csv"
            print(f"  [{i}/{len(raster_files)}] {rp.name} -> {out.name}")
            try:
                result = self.zonal_stats(
                    raster_path=rp,
                    vector_path=vector_path,
                    output_path=out,
                    id_field=id_field,
                    stats_list=stats_list,
                    nodata=nodata,
                )
                results.append(result)
            except Exception as e:
                print(f"    ERROR: {e}")

        print(f"Batch complete: {len(results)}/{len(raster_files)} succeeded")
        return results

    # ----- Layer loading -----

    def _load_layer(self, layer_id: str) -> Optional[gpd.GeoDataFrame]:
        if layer_id in self._cache:
            return self._cache[layer_id]
        path = self.registry.get_data_path(layer_id)
        if path is None:
            return None
        gdf = gpd.read_parquet(path)
        self._cache[layer_id] = gdf
        return gdf

    def clear_cache(self) -> None:
        self._cache.clear()

    @staticmethod
    def _normalize_geometry(geometry):
        """Normalize various geometry inputs to shapely geometry."""
        if isinstance(geometry, str):
            try:
                return wkt.loads(geometry)
            except Exception:
                import json
                geom_dict = json.loads(geometry)
                return shape(geom_dict)
        if isinstance(geometry, dict):
            return shape(geometry)
        return geometry
