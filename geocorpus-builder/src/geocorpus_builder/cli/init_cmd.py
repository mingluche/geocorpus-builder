"""geocorpus init -- initialize a new GeoCorpus project directory."""

from pathlib import Path

import click

from ..config.project import GeoCorpusProject


@click.command()
@click.argument("path", type=click.Path(), default=".")
@click.option("--domain", default="cryosphere", help="Scientific domain")
@click.option("--subdomain", default="glacier", help="Subdomain")
def init(path: str, domain: str, subdomain: str) -> None:
    """Initialize a new GeoCorpus project directory.

    Creates the directory structure, writes a config file, and copies
    seed data files from the bundled Agent Pack into the project.
    """
    project_path = Path(path).resolve()
    if project_path.exists() and list(project_path.iterdir()):
        click.confirm(
            f"Directory '{project_path}' is not empty. Continue?",
            abort=True,
        )

    project = GeoCorpusProject.init(project_path, domain=domain, subdomain=subdomain)

    click.echo(f"GeoCorpus project initialized at: {project.root}")
    click.echo(f"  Domain:      {domain}")
    click.echo(f"  Subdomain:   {subdomain}")
    click.echo(f"  Config:      {project.root / 'geocorpus_config.json'}")
    click.echo(f"  Data dir:    {project.root / project.config.data_dir}")
    click.echo(f"  Corpus dir:  {project.root / project.config.corpus_dir}")
    click.echo(f"  Evidence dir:{project.root / project.config.evidence_dir}")
