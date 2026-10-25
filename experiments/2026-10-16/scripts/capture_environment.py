"""Capture the unchanged software and execution environment for an experiment."""

from __future__ import annotations

import argparse
import hashlib
import importlib.metadata
import json
import platform
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

import psutil


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[3]
    repo = root / "geocorpus-builder"
    paths = sorted((repo / "src").rglob("*.py")) + [repo / "pyproject.toml"]
    hashes = {
        str(path.relative_to(repo)).replace("\\", "/"): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in paths
    }
    packages = ["numpy", "pandas", "pyarrow", "geopandas", "shapely", "rasterio", "pydantic", "psutil"]
    cpu_name = platform.processor()
    if sys.platform == "win32":
        import winreg
        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, r"HARDWARE\DESCRIPTION\System\CentralProcessor\0") as key:
            cpu_name = winreg.QueryValueEx(key, "ProcessorNameString")[0].strip()
    record = {
        "captured_at_utc": datetime.now(timezone.utc).isoformat(),
        "python": sys.version,
        "executable": sys.executable,
        "platform": platform.platform(),
        "processor": platform.processor(),
        "cpu_name": cpu_name,
        "logical_cpus": psutil.cpu_count(),
        "physical_cpus": psutil.cpu_count(logical=False),
        "total_ram_bytes": psutil.virtual_memory().total,
        "packages": {name: importlib.metadata.version(name) for name in packages},
        "source_sha256": hashes,
        "git_status": subprocess.run(
            ["git", "status", "--short"], cwd=repo, capture_output=True, text=True, encoding="utf-8"
        ).stdout,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(record, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"output": str(args.output), "files_hashed": len(hashes), "logical_cpus": record["logical_cpus"], "ram_gib": record["total_ram_bytes"] / 2**30}))


if __name__ == "__main__":
    main()
