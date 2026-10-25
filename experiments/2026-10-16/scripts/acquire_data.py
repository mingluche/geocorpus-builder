"""Acquire real official data without downloading multi-GB ZIP archives.

Only HTTP 206 byte ranges are accepted for remote ZIP reads. Extracted ZIP
members keep their original bytes; derived vector subsets are clearly separate.
"""

from __future__ import annotations

import argparse
import hashlib
import io
import json
import re
import time
import zipfile
import zlib
from collections import OrderedDict
from datetime import datetime, timezone
from pathlib import Path

import requests


ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"
BASIN_URL = "https://ndownloader.figshare.com/files/20087237"
WORLD_BASE = "https://geodata.ucdavis.edu/climate/worldclim/2_1/base/"
SOURCES = {
    "basinatlas": BASIN_URL,
    "tavg": WORLD_BASE + "wc2.1_2.5m_tavg.zip",
    "prec": WORLD_BASE + "wc2.1_2.5m_prec.zip",
    "elev": WORLD_BASE + "wc2.1_2.5m_elev.zip",
}


def utc_now():
    return datetime.now(timezone.utc).isoformat()


def save_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")
    temporary.replace(path)


def sha256(path):
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(4 * 1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def crc32(path):
    value = 0
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(4 * 1024 * 1024), b""):
            value = zlib.crc32(chunk, value)
    return f"{value & 0xffffffff:08x}"


class RemoteRangeFile(io.RawIOBase):
    def __init__(self, url, block_size=8 * 1024 * 1024):
        super().__init__()
        self.url = url
        self.session = requests.Session()
        self.session.headers.update({"User-Agent": "GeoCorpus-real-case-acquisition/1.0"})
        self.position = 0
        self.transferred = 0
        self.block_size = block_size
        self.cache = OrderedDict()
        self.headers = {}
        self.resolved_url = None
        payload, headers = self._range(0, 0)
        match = re.fullmatch(r"bytes 0-0/(\d+)", headers.get("Content-Range", ""))
        if not match or len(payload) != 1:
            raise RuntimeError("Source does not provide a valid one-byte Content-Range")
        self.size = int(match.group(1))

    def _range(self, start, end):
        for attempt in range(4):
            try:
                with self.session.get(
                    self.url,
                    headers={"Range": f"bytes={start}-{end}", "Accept-Encoding": "identity"},
                    timeout=(30, 180), stream=True,
                ) as response:
                    if response.status_code != 206:
                        raise RuntimeError(f"Range rejected: HTTP {response.status_code}; no full download attempted")
                    content_range = response.headers.get("Content-Range", "")
                    if not content_range.startswith(f"bytes {start}-{end}/"):
                        raise RuntimeError(f"Unexpected Content-Range: {content_range}")
                    value = response.content
                    if len(value) != end - start + 1:
                        raise RuntimeError("Incomplete HTTP range")
                    self.transferred += len(value)
                    self.headers = {
                        name: response.headers.get(name)
                        for name in ("Last-Modified", "ETag", "Content-Range", "Content-Type")
                    }
                    self.resolved_url = response.url.split("?", 1)[0]
                    return value, response.headers
            except Exception:
                if attempt == 3:
                    raise
                time.sleep(2 ** attempt)

    def readable(self):
        return True

    def seekable(self):
        return True

    def tell(self):
        return self.position

    def seek(self, offset, whence=0):
        if whence == 0:
            self.position = offset
        elif whence == 1:
            self.position += offset
        elif whence == 2:
            self.position = self.size + offset
        else:
            raise ValueError(whence)
        if self.position < 0:
            raise ValueError("Negative position")
        return self.position

    def read(self, size=-1):
        if size < 0:
            size = self.size - self.position
        size = min(size, self.size - self.position)
        chunks = []
        while size > 0:
            block = self.position // self.block_size
            start = block * self.block_size
            end = min(start + self.block_size, self.size) - 1
            if block not in self.cache:
                self.cache[block] = self._range(start, end)[0]
                while len(self.cache) > 3:
                    self.cache.popitem(last=False)
            self.cache.move_to_end(block)
            offset = self.position - start
            length = min(size, len(self.cache[block]) - offset)
            chunks.append(self.cache[block][offset:offset + length])
            self.position += length
            size -= length
        return b"".join(chunks)

    def close(self):
        self.session.close()
        super().close()


def choose_members(kind, archive):
    if kind == "basinatlas":
        suffixes = {".shp", ".dbf", ".shx", ".prj", ".cpg"}
        chosen = [
            item for item in archive.infolist()
            if re.search(r"_lev0?6\.", item.filename, re.IGNORECASE)
            and Path(item.filename).suffix.lower() in suffixes
        ]
        found = {Path(item.filename).suffix.lower() for item in chosen}
        if not {".shp", ".dbf", ".shx", ".prj"}.issubset(found):
            raise RuntimeError(f"Level 6 components unavailable: {found}")
        return chosen
    chosen = [
        item for item in archive.infolist()
        if item.filename.lower().endswith(".tif")
        and (kind == "elev" or re.search(r"_(01|07)\.tif$", item.filename))
    ]
    expected = 1 if kind == "elev" else 2
    if len(chosen) != expected:
        raise RuntimeError(f"Expected {expected} {kind} members, got {len(chosen)}")
    return chosen


def acquire_source(kind, inspect_only=False):
    source = SOURCES[kind]
    start = utc_now()
    block_size = 65536 if inspect_only else 8 * 1024 * 1024
    with RemoteRangeFile(source, block_size=block_size) as remote, zipfile.ZipFile(remote) as archive:
        selected = choose_members(kind, archive)
        plan = {
            "source_url": source, "resolved_source_url": remote.resolved_url,
            "archive_bytes": remote.size, "http_headers": remote.headers,
            "members": [
                {"name": entry.filename, "compressed_bytes": entry.compress_size,
                 "uncompressed_bytes": entry.file_size, "zip_crc32": f"{entry.CRC:08x}",
                 "zip_member_time": list(entry.date_time)}
                for entry in selected
            ],
        }
        save_json(DATA / "audit" / f"{kind}_remote_zip_plan.json", plan)
        print(json.dumps({"kind": kind, **plan}, ensure_ascii=False), flush=True)
        if sum(item.compress_size for item in selected) > 600 * 1024 * 1024:
            raise RuntimeError("Selected members exceed 600 MiB; approval/review required")
        if inspect_only:
            return []
        records = []
        target_dir = DATA / "raw" / kind
        target_dir.mkdir(parents=True, exist_ok=True)
        for item in selected:
            destination = target_dir / Path(item.filename).name
            if destination.exists() and destination.stat().st_size == item.file_size:
                print(f"Existing member retained: {destination.name}", flush=True)
            else:
                partial = destination.with_suffix(destination.suffix + ".partial")
                with archive.open(item) as input_file, partial.open("wb") as output_file:
                    while True:
                        chunk = input_file.read(2 * 1024 * 1024)
                        if not chunk:
                            break
                        output_file.write(chunk)
                if partial.stat().st_size != item.file_size:
                    raise RuntimeError(f"Extracted size mismatch: {item.filename}")
                partial.replace(destination)
            record = {
                "path": destination.relative_to(DATA).as_posix(),
                "source_url": source, "resolved_source_url": remote.resolved_url,
                "zip_member": item.filename, "zip_crc32": f"{item.CRC:08x}",
                "bytes": destination.stat().st_size, "sha256": sha256(destination),
                "acquisition_started_utc": start, "acquisition_completed_utc": utc_now(),
                "source_headers": remote.headers,
            }
            if crc32(destination) != record["zip_crc32"]:
                raise RuntimeError(f"ZIP CRC32 mismatch: {destination}")
            record["zip_crc32_verified"] = True
            records.append(record)
            save_json(DATA / "audit" / f"{kind}_files.json", records)
            print(f"Saved {destination.name}: {record['bytes']} bytes sha256={record['sha256']}", flush=True)
        save_json(DATA / "audit" / f"{kind}_transfer.json", {
            "source_url": source, "archive_bytes": remote.size,
            "http_range_payload_bytes": remote.transferred, "completed_utc": utc_now(),
        })
        return records


def validate_and_manifest():
    import geopandas as gpd
    import numpy as np
    import rasterio

    vector_path = next((DATA / "raw" / "basinatlas").glob("*.shp"))
    frame = gpd.read_file(vector_path)
    id_field = next(name for name in frame.columns if name.lower() == "hybas_id")
    asia = frame[frame[id_field].astype(str).str.startswith("4")].copy()
    if len(asia) < 1000:
        raise RuntimeError(f"Too few Asian sub-basins: {len(asia)}")
    derived_dir = DATA / "derived" / "basinatlas_asia_level6"
    derived_dir.mkdir(parents=True, exist_ok=True)
    asia_path = derived_dir / "BasinATLAS_v10_lev06_asia.shp"
    asia.to_file(asia_path, index=False)
    attributes = [name for name in ("SUB_AREA", "UP_AREA", "ele_mt_sav", "ele_mt_smn", "ele_mt_smx") if name in asia]
    if not {"SUB_AREA", "ele_mt_sav"}.issubset(attributes):
        raise RuntimeError(f"Required attributes missing: {list(asia.columns)}")
    vector = {
        "path": asia_path.relative_to(DATA).as_posix(), "layer": None,
        "id_field": id_field, "name_field": None, "attributes": attributes,
        "units": {name: "km2" if name.endswith("AREA") else "m" for name in attributes},
        "time_range": "static; source periods differ by attribute", "source": BASIN_URL,
        "version": "BasinATLAS 1.0, Pfafstetter level 6",
        "raw_path": vector_path.relative_to(DATA).as_posix(),
        "subset_rule": "HYBAS_ID first digit = 4 (Asia), official HydroATLAS region code",
        "geographic_scope_note": "HydroATLAS Asia code 4; Siberia is separately coded 3 and is not included.",
        "feature_count": len(asia), "global_level6_feature_count": len(frame),
        "crs": str(asia.crs), "bounds": asia.total_bounds.tolist(),
        "geometry_types": asia.geom_type.value_counts().to_dict(),
        "valid_geometry_count": int(asia.is_valid.sum()),
        "invalid_geometry_count": int((~asia.is_valid).sum()),
        "empty_geometry_count": int(asia.is_empty.sum()),
        "invalid_geometry_ids": [int(value) for value in asia.loc[~asia.is_valid, id_field]],
        "geometry_repair_applied": False,
        "id_is_unique": bool(asia[id_field].is_unique),
        "component_sha256": {path.name: sha256(path) for path in sorted(derived_dir.glob("*"))},
        "attribute_scaling": {name: {"scale": 1, "offset": 0} for name in attributes},
        "all_fields": {name: str(dtype) for name, dtype in asia.dtypes.items()},
        "numeric_ranges": {
            name: {"min": float(asia[name].min()), "max": float(asia[name].max()),
                   "missing": int(asia[name].isna().sum())}
            for name in attributes
        },
    }
    rasters = []
    for kind in ("tavg", "prec", "elev"):
        for path in sorted((DATA / "raw" / kind).glob("*.tif")):
            with rasterio.open(path) as dataset:
                sample = dataset.read(1, out_shape=(256, 512), masked=True)
                values = sample.compressed()
                values = values[np.isfinite(values)]
                if dataset.count != 1 or not len(values):
                    raise RuntimeError(f"Raster unreadable, multiband, or empty: {path}")
                month = int(path.stem.rsplit("_", 1)[1]) if kind != "elev" else None
                raster = {
                    "path": path.relative_to(DATA).as_posix(),
                    "variable": f"{kind}_{month:02d}" if month else "elevation",
                    "unit": {"tavg": "degC", "prec": "mm", "elev": "m"}[kind],
                    "time_range": "1970-2000 monthly climatology" if month else "static (SRTM-derived)",
                    "month": month, "source": SOURCES[kind], "version": "WorldClim 2.1",
                    "crs": str(dataset.crs), "width": dataset.width, "height": dataset.height,
                    "bounds": list(dataset.bounds), "resolution": list(dataset.res),
                    "transform": list(dataset.transform), "dtype": dataset.dtypes[0],
                    "count": dataset.count,
                    "nodata": float(dataset.nodata) if dataset.nodata is not None else None,
                    "scales": list(dataset.scales), "offsets": list(dataset.offsets),
                    "dataset_units": list(dataset.units), "tags": dataset.tags(),
                    "band_tags": dataset.tags(1), "sha256": sha256(path),
                    "sample_min": float(values.min()), "sample_max": float(values.max()),
                    "sample_shape": [256, 512], "sample_not_global_extrema": True,
                }
                rasters.append(raster)
    if len(rasters) != 5:
        raise RuntimeError(f"Expected five rasters, got {len(rasters)}")
    audited_files = []
    for audit_path in sorted((DATA / "audit").glob("*_files.json")):
        records = json.loads(audit_path.read_text(encoding="utf-8"))
        for record in records:
            path = DATA / record["path"]
            if sha256(path) != record["sha256"] or crc32(path) != record["zip_crc32"]:
                raise RuntimeError(f"Audit hash/CRC verification failed: {path}")
            record["zip_crc32_verified"] = True
            audited_files.append(record["path"])
        save_json(audit_path, records)
    save_json(DATA / "audit" / "validation_summary.json", {
        "validated_utc": utc_now(), "raw_file_count": len(audited_files),
        "all_raw_sha256_and_zip_crc32_verified": True,
        "raw_total_bytes": sum((DATA / name).stat().st_size for name in audited_files),
        "asia_feature_count": len(asia), "global_level6_feature_count": len(frame),
        "valid_geometry_count": int(asia.is_valid.sum()),
        "invalid_geometry_count": int((~asia.is_valid).sum()),
        "geometry_repair_applied": False,
        "vector_subset_reopened": len(gpd.read_file(asia_path)) == len(asia),
        "raster_count": len(rasters),
    })
    manifest = {
        "created_utc": utc_now(), "status": "downloaded_and_opened",
        "vector": vector, "rasters": rasters,
        "official_documentation": {
            "hydroatlas": "https://www.hydrosheds.org/hydroatlas",
            "hydroatlas_technical": "https://data.hydrosheds.org/file/technical-documentation/HydroATLAS_TechDoc_v10_1.pdf",
            "worldclim": "https://www.worldclim.org/data/worldclim21.html",
            "worldclim_license": "https://worldclim.org/about.html",
        },
        "license_notes": [
            "HydroATLAS collective database CC-BY 4.0; individual attributes CC-BY 4.0 or ODbL 1.0; retain source attribution.",
            "WorldClim academic/non-commercial use; redistribution or commercial use requires prior permission.",
            "These WorldClim climate files are monthly 1970-2000 normals, not annual observed time series.",
        ],
        "unit_provenance": {
            "basinatlas_area_elevation": "HydroATLAS technical documentation unit keys and spatial/statistical suffix definitions; selected elevation fields use meters and area fields use km2.",
            "worldclim_tavg_prec": "WorldClim 2.1 download page states temperature in degC and precipitation in mm; actual TIFF scales=1 and offsets=0.",
            "worldclim_elevation": "WorldClim 2.1 identifies this layer as SRTM-derived; SRTM vertical units are meters (USGS product documentation). No original SRTM version is asserted.",
            "srtm_vertical_units_source": "https://www.usgs.gov/centers/eros/science/usgs-eros-archive-digital-elevation-shuttle-radar-topography-mission-srtm",
            "caution": "GeoTIFF dataset_units are unset; physical units are taken from source documentation, not inferred solely from values.",
        },
    }
    save_json(DATA / "real_case_manifest.json", manifest)
    print(f"MANIFEST_READY {DATA / 'real_case_manifest.json'}; Asia objects={len(asia)}, rasters={len(rasters)}", flush=True)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--inspect", action="store_true")
    parser.add_argument("--only", choices=["all", *SOURCES], default="all")
    parser.add_argument("--validate-only", action="store_true")
    args = parser.parse_args()
    DATA.mkdir(parents=True, exist_ok=True)
    if not args.validate_only:
        for kind in SOURCES if args.only == "all" else [args.only]:
            acquire_source(kind, args.inspect)
    if not args.inspect and (args.only == "all" or args.validate_only):
        validate_and_manifest()


if __name__ == "__main__":
    main()
