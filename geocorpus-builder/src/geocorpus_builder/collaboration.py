"""Collaboration: export and merge GeoCorpus project data for multi-team workflows."""

from __future__ import annotations

import json
import shutil
import tarfile
from datetime import datetime
from pathlib import Path
from typing import Optional


def export_project(project_root: Path, output_path: Path,
                   include_data: bool = True) -> Path:
    """Export a project's corpus, evidence, and config as a shareable tar.gz.

    Args:
        project_root: Path to the GeoCorpus project directory.
        output_path: Output tar.gz file path.
        include_data: If True, also include statistics/ and data/ directories.

    Returns:
        Path to the created archive.
    """
    project_root = project_root.resolve()
    output_path = output_path.resolve()
    output_path.parent.mkdir(parents=True, exist_ok=True)

    files_to_pack: list[tuple[Path, str]] = []

    # Always include
    for sub in ["corpus", "evidence"]:
        subdir = project_root / sub
        if subdir.exists():
            for f in subdir.glob("*"):
                if f.is_file():
                    files_to_pack.append((f, f"{sub}/{f.name}"))

    # Config
    config_path = project_root / "geocorpus_config.json"
    if config_path.exists():
        files_to_pack.append((config_path, "geocorpus_config.json"))

    # Templates
    tmpl_dir = project_root / "templates"
    if tmpl_dir.exists():
        for f in tmpl_dir.glob("*"):
            if f.is_file():
                files_to_pack.append((f, f"templates/{f.name}"))

    # Statistics and data (optional)
    if include_data:
        for sub in ["statistics", "data"]:
            subdir = project_root / sub
            if subdir.exists():
                for f in subdir.glob("*"):
                    if f.is_file() and f.suffix not in (".geoparquet", ".meta.json"):
                        files_to_pack.append((f, f"{sub}/{f.name}"))

    # Manifest
    manifest = {
        "exported_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "project_root": str(project_root),
        "files": [arcname for _, arcname in files_to_pack],
    }

    count = 0
    with tarfile.open(output_path, "w:gz") as tar:
        for real_path, arcname in files_to_pack:
            tar.add(real_path, arcname=arcname)
            count += 1

        # Add manifest
        manifest_bytes = json.dumps(manifest, ensure_ascii=False, indent=2).encode("utf-8")
        import tarfile as tf
        info = tf.TarInfo(name="manifest.json")
        info.size = len(manifest_bytes)
        tar.addfile(info, __import__("io").BytesIO(manifest_bytes))

    print(f"Exported {count} files to: {output_path} ({output_path.stat().st_size / 1024:.0f} KB)")
    return output_path


def merge_into_project(project_root: Path, source_path: Path,
                       strategy: str = "skip") -> dict:
    """Merge corpus/evidence data from another project or export archive into this one.

    Args:
        project_root: Target project directory.
        source_path: Source project directory or exported tar.gz.
        strategy: 'skip' (skip duplicates), 'overwrite' (replace existing),
                  'rename' (add _merged suffix).

    Returns:
        Dict with merge statistics.
    """
    project_root = project_root.resolve()
    source_path = source_path.resolve()

    if source_path.suffix in (".gz", ".tgz", ".tar"):
        return _merge_from_archive(project_root, source_path, strategy)
    else:
        return _merge_from_dir(project_root, source_path, strategy)


def _merge_from_archive(project_root: Path, archive_path: Path,
                        strategy: str) -> dict:
    stats = {"corpus_added": 0, "evidence_added": 0, "skipped": 0, "overwritten": 0}

    with tarfile.open(archive_path, "r:gz") as tar:
        for member in tar.getmembers():
            if member.name.startswith("corpus/") and member.name.endswith(".jsonl"):
                dest = project_root / member.name
                stats.update(_merge_jsonl(dest, tar, member, strategy))
            elif member.name.startswith("evidence/") and member.name.endswith(".jsonl"):
                dest = project_root / member.name
                stats.update(_merge_jsonl(dest, tar, member, strategy))

    return stats


def _merge_from_dir(project_root: Path, source_dir: Path,
                    strategy: str) -> dict:
    stats = {"corpus_added": 0, "evidence_added": 0, "skipped": 0, "overwritten": 0}

    for sub in ["corpus", "evidence"]:
        src_sub = source_dir / sub
        dst_sub = project_root / sub
        if not src_sub.exists():
            continue
        dst_sub.mkdir(parents=True, exist_ok=True)
        for f in src_sub.glob("*.jsonl"):
            dest = dst_sub / f.name
            records_src = _read_jsonl(f)
            records_dst = _read_jsonl(dest) if dest.exists() else []
            merged, added, skipped, overwritten = _merge_records(
                records_src, records_dst, strategy
            )
            _write_jsonl(merged, dest)
            stats["corpus_added" if sub == "corpus" else "evidence_added"] += added
            stats["skipped"] += skipped
            stats["overwritten"] += overwritten

    return stats


def _merge_jsonl(dest: Path, tar, member, strategy: str) -> dict:
    records_src = _read_jsonl(None, tar.extractfile(member))
    records_dst = _read_jsonl(dest) if dest.exists() else []
    merged, added, skipped, overwritten = _merge_records(records_src, records_dst, strategy)
    dest.parent.mkdir(parents=True, exist_ok=True)
    _write_jsonl(merged, dest)
    return {"corpus_added": added if "corpus" in str(dest) else 0,
            "evidence_added": added if "evidence" in str(dest) else 0,
            "skipped": skipped, "overwritten": overwritten}


def _merge_records(src: list[dict], dst: list[dict], strategy: str):
    """Merge records with deduplication by corpus_id / evidence_id."""
    id_field = "corpus_id" if src and "corpus_id" in src[0] else "evidence_id"
    dst_ids = {r.get(id_field) for r in dst}
    added = 0
    skipped = 0
    overwritten = 0

    for r in src:
        rid = r.get(id_field)
        if rid and rid in dst_ids:
            if strategy == "overwrite":
                dst = [x for x in dst if x.get(id_field) != rid] + [r]
                overwritten += 1
            elif strategy == "rename":
                r[id_field] = f"{rid}_merged_{skipped + 1}"
                dst.append(r)
                added += 1
            else:  # skip
                skipped += 1
        else:
            dst.append(r)
            added += 1

    return dst, added, skipped, overwritten


def _read_jsonl(path, fileobj=None) -> list[dict]:
    records = []
    if fileobj:
        for line in fileobj.read().decode("utf-8").splitlines():
            line = line.strip()
            if line:
                records.append(json.loads(line))
    elif path and path.exists():
        with open(path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line:
                    records.append(json.loads(line))
    return records


def _write_jsonl(records: list[dict], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        for r in records:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
