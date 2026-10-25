"""GeoCorpus Builder CLI -- entry point."""

import click

from .cli.init_cmd import init
from .cli.validate_cmd import validate
from .cli.build_cmd import build
from .cli.ingest_cmd import ingest, ingest_dir
from .cli.query_cmd import query
from .cli.spatial_cmd import spatial
from .cli.collab_cmd import export_cmd, merge_cmd
from .cli.pipeline_cmd import pipeline


@click.group()
@click.version_option(version="0.1.0")
def cli():
    """GeoCorpus Builder: build, validate, and query geographically grounded Earth-science corpora.

    Core workflow:
      1. geocorpus init      -- create a new project
      2. geocorpus ingest    -- import data into evidence_links
      3. geocorpus build     -- generate corpus units from data tables
      4. geocorpus validate  -- check data quality
      5. geocorpus query     -- ask questions grounded in evidence
    """
    pass


cli.add_command(init)
cli.add_command(validate)
cli.add_command(build)
cli.add_command(ingest)
cli.add_command(ingest_dir, name="ingest-dir")
cli.add_command(pipeline)
cli.add_command(query)
cli.add_command(spatial)
cli.add_command(export_cmd, name="export")
cli.add_command(merge_cmd, name="merge")


@cli.command("gui")
@click.option("--port", default=8501, help="Web server port")
@click.option("--headless", is_flag=True, default=False, help="Don't open browser")
def gui(port: int, headless: bool) -> None:
    """Launch the GeoCorpus Builder web GUI."""
    import sys
    from pathlib import Path

    gui_script = Path(__file__).parent / "gui.py"
    args = ["streamlit", "run", str(gui_script), "--server.port", str(port)]
    if headless:
        args.append("--server.headless=true")

    import subprocess
    subprocess.run(args)
