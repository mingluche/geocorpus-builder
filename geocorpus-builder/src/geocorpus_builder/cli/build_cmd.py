"""geocorpus build -- generate corpus units from data tables."""

from pathlib import Path

import click

from ..builder.engine import BuildOrchestrator
from ..config.project import GeoCorpusProject


@click.command()
@click.option("--project", "-p", "project_path", type=click.Path(exists=True), default=".",
              help="Path to GeoCorpus project directory")
@click.option("--tables", "-t", multiple=True,
              help="Extra tables as name=path (e.g. glacier_yearly_stats=./stats.parquet)")
@click.option("--output", "-o", "output_dir", type=click.Path(), default=None,
              help="Output directory for generated files")
@click.option("--spatial-enrich", is_flag=True, default=False,
              help="Auto-assign spatial regions to each geo_object using bundled boundary data")
@click.option("--id-prefix", default="GC_BUILT", help="Prefix for generated corpus IDs (use team name to avoid collisions)")
def build(project_path: str, tables: tuple[str, ...], output_dir: str | None,
          spatial_enrich: bool, id_prefix: str) -> None:
    """Build corpus units and evidence links from data tables.

    Reads statistics tables (Parquet/CSV) and generates natural-language
    corpus units with linked evidence records, following the project's
    build profile (currently: glacier).

    Output is written to corpus/corpus_units.jsonl and
    evidence/evidence_links.jsonl in the project directory.
    """
    proj_dir = Path(project_path).resolve()
    project = GeoCorpusProject.discover(proj_dir)

    # Parse extra tables
    table_map: dict[str, Path] = {}
    for entry in tables:
        if "=" in entry:
            name, path_str = entry.split("=", 1)
            table_map[name.strip()] = Path(path_str.strip()).resolve()

    output = Path(output_dir).resolve() if output_dir else None

    orchestrator = BuildOrchestrator(project)
    orchestrator.build(tables=table_map if table_map else None, output=output,
                       spatial_enrich=spatial_enrich, id_prefix=id_prefix)
