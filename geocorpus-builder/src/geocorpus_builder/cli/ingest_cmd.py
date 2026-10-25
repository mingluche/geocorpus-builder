"""geocorpus ingest -- import data into evidence_links."""

from pathlib import Path

import click

from ..ingest import ingest_raster_zonal_stats, ingest_vector_attributes, ingest_crosswalk


@click.command()
@click.argument("input_path", type=click.Path(exists=True))
@click.option("--type", "-t", "ingest_type",
              type=click.Choice(["raster", "vector", "crosswalk"]),
              required=True, help="Type of data being ingested")
@click.option("--output", "-o", type=click.Path(), default=None,
              help="Output path for evidence_links JSONL")
@click.option("--zone-field", default="glacier_id",
              help="Field name for zone/object ID (raster ingest)")
@click.option("--variable", "-v", default="glacier_thickness",
              help="Variable name")
@click.option("--time-range", default="", help="Time range string")
def ingest(input_path: str, ingest_type: str, output: str | None,
           zone_field: str, variable: str, time_range: str) -> None:
    """Ingest data from raster/vector/crosswalk files into evidence_links.

    Reads statistics from raster zonal stats, vector attribute tables, or
    spatial crosswalk tables and converts them to evidence_links JSONL records.
    """
    in_path = Path(input_path).resolve()
    out_path = Path(output).resolve() if output else in_path.with_suffix(".evidence.jsonl")

    if ingest_type == "raster":
        ingest_raster_zonal_stats(in_path, out_path,
                                  zone_field=zone_field, variable=variable,
                                  time_range=time_range)
    elif ingest_type == "vector":
        ingest_vector_attributes(in_path, out_path,
                                 id_field=zone_field, variable=variable,
                                 time_range=time_range)
    elif ingest_type == "crosswalk":
        ingest_crosswalk(in_path, out_path)


@click.command(name="ingest-dir")
@click.argument("stats_dir", type=click.Path(exists=True))
@click.option("--project", "-p", "project_path", type=click.Path(), default=".",
              help="Target project directory")
@click.option("--variable", "-v", default="", help="Variable name (auto-detect from filename if empty)")
@click.option("--time-range", default="", help="Time range")
@click.option("--pattern", default="*.csv", help="Glob pattern for stat files")
def ingest_dir(stats_dir: str, project_path: str, variable: str,
               time_range: str, pattern: str) -> None:
    """Ingest all CSV/Parquet stat files in a directory into evidence_links.

    Copies files to the project's statistics/ dir and runs ingest on each.
    Variable name is auto-detected from the filename stem if not specified.

    \b
    Example:
        geocorpus ingest-dir D:/data/stats/ -p my_project --time-range 2024
    """
    from pathlib import Path
    import shutil
    from ..ingest import ingest_raster_zonal_stats, ingest_vector_attributes

    proj_root = Path(project_path).resolve()
    src_dir = Path(stats_dir).resolve()
    dest_dir = proj_root / "statistics"
    dest_dir.mkdir(parents=True, exist_ok=True)

    count = 0
    for f in sorted(src_dir.glob(pattern)):
        var = variable or f.stem
        tr = time_range
        import re
        year_match = re.search(r'(\d{4})', f.stem)
        if not tr and year_match:
            tr = year_match.group(1)

        # Copy to project statistics/ dir (build reads from here)
        dest = dest_dir / f.name
        shutil.copy2(f, dest)
        count += 1
        click.echo(f"  [{count}] {f.name} -> {dest}")

    click.echo(f"Copied {count} files into {dest_dir}")
    click.echo(f"Next: geocorpus build -p {proj_root} --spatial-enrich")
