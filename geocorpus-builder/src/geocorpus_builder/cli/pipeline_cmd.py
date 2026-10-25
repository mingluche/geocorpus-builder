"""geocorpus pipeline -- full chain from raster directory to queryable corpus."""

import shutil
from pathlib import Path

import click

from ..spatial import SpatialQueryEngine
from ..config.project import GeoCorpusProject
from ..builder.engine import BuildOrchestrator
from ..ingest import ingest_raster_zonal_stats


@click.command(name="pipeline")
@click.option("--raster-dir", "-r", type=click.Path(exists=True), required=True,
              help="Directory containing TIFF/NC raster files")
@click.option("--vector", "-v", type=click.Path(exists=True), required=True,
              help="Boundary SHP file for zonal statistics")
@click.option("--project", "-p", "project_path", type=click.Path(), required=True,
              help="GeoCorpus project directory (created if not exists)")
@click.option("--id-field", default="glacier_id", help="ID field in boundary vector")
@click.option("--pattern", default="*.tif,*.nc", help="Glob pattern for raster files")
@click.option("--domain", default="cryosphere", help="Scientific domain")
@click.option("--subdomain", default="glacier", help="Subdomain")
@click.option("--id-prefix", default="GC_BUILT", help="Corpus ID prefix")
@click.option("--skip-build", is_flag=True, default=False,
              help="Only do zonal-stats + ingest, skip build")
def pipeline(raster_dir, vector, project_path, id_field, pattern,
             domain, subdomain, id_prefix, skip_build):
    """Run the full production pipeline: TIFFs -> zonal stats -> ingest -> build.

    \b
    Steps:
      1. batch-zonal-stats: all rasters × boundary → CSV statistics
      2. ingest-dir: all CSVs → evidence_links
      3. build --spatial-enrich: generate corpus units with spatial attribution

    \b
    Example:
        geocorpus pipeline -r D:/data/rasters/ -v glacier_boundary.shp \\
            -p D:/work/my_project --id-prefix TEAM_A
    """
    proj_dir = Path(project_path).resolve()
    raster_dir_p = Path(raster_dir).resolve()
    vector_p = Path(vector).resolve()

    # 1. Init project if needed
    if not (proj_dir / "geocorpus_config.json").exists():
        click.echo("=== Step 1/4: Init project ===")
        GeoCorpusProject.init(proj_dir, domain=domain, subdomain=subdomain)

    tmp_stats = proj_dir / "_tmp_stats"
    stats_dest = proj_dir / "statistics"

    # 2. Batch zonal-stats
    click.echo(f"\n=== Step 2/4: Batch zonal-stats ({len(list(raster_dir_p.glob(pattern)))} rasters) ===")
    engine = SpatialQueryEngine()
    csv_paths = engine.batch_zonal_stats(
        raster_dir=raster_dir_p, vector_path=vector_p,
        output_dir=tmp_stats, id_field=id_field, pattern=pattern,
    )

    if not csv_paths:
        click.echo("No CSV files generated. Aborting.")
        return

    # 3. Move CSVs + ingest
    click.echo(f"\n=== Step 3/4: Ingest {len(csv_paths)} stat files ===")
    stats_dest.mkdir(parents=True, exist_ok=True)
    import re

    for csv_path in csv_paths:
        dest = stats_dest / csv_path.name
        shutil.move(str(csv_path), str(dest))
        var = csv_path.stem
        tr = ""
        m = re.search(r'(\d{4})', csv_path.stem)
        if m:
            tr = m.group(1)
        out = proj_dir / "evidence" / f"{csv_path.stem}.evidence.jsonl"
        try:
            ingest_raster_zonal_stats(dest, out, variable=var, time_range=tr)
            click.echo(f"  {csv_path.name} -> var={var} time={tr}")
        except Exception as e:
            click.echo(f"  ERR: {csv_path.name}: {e}")

    shutil.rmtree(tmp_stats, ignore_errors=True)

    # 4. Build
    if not skip_build:
        click.echo("\n=== Step 4/4: Build corpus ===")
        project = GeoCorpusProject.discover(proj_dir)
        orch = BuildOrchestrator(project)
        report = orch.build(spatial_enrich=True, id_prefix=id_prefix)
        click.echo(f"Complete: {report.units_created} units, {report.evidence_created} evidence")

    click.echo(f"\nPipeline done. Project: {proj_dir}")
    click.echo(f"Next: geocorpus validate {proj_dir}")
    click.echo(f"      geocorpus query -p {proj_dir} -q \"your question\"")
