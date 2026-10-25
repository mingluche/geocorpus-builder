"""geocorpus export / merge -- multi-team collaboration commands."""

from pathlib import Path

import click

from ..collaboration import export_project, merge_into_project


@click.command()
@click.argument("project_path", type=click.Path(exists=True), default=".")
@click.option("--output", "-o", type=click.Path(), required=True,
              help="Output tar.gz path")
@click.option("--no-data", is_flag=True, default=False,
              help="Exclude statistics/ and data/ from export")
def export_cmd(project_path: str, output: str, no_data: bool) -> None:
    """Export a project's corpus, evidence, and config as a shareable tar.gz.

    Packages all corpus_units.jsonl, evidence_links.jsonl, config,
    and templates into a compressed archive that can be shared with
    other team members.

    \b
    Example:
        geocorpus export ./my_project -o shared/glacier_v1.tar.gz
    """
    export_project(Path(project_path), Path(output), include_data=not no_data)
    click.echo(f"Share with: geocorpus merge {output} -p target_project/")


@click.command()
@click.argument("source", type=click.Path(exists=True))
@click.option("--project", "-p", "project_path", type=click.Path(), default=".",
              help="Target project directory")
@click.option("--strategy", "-s", type=click.Choice(["skip", "overwrite", "rename"]),
              default="skip", help="How to handle duplicate IDs")
def merge_cmd(source: str, project_path: str, strategy: str) -> None:
    """Merge corpus/evidence data from another project or export archive.

    Source can be a project directory or an exported .tar.gz archive.
    By default, records with duplicate IDs are skipped.

    \b
    Merge strategies:
      skip       - Skip records with existing IDs (safe default)
      overwrite  - Replace existing records with the same ID
      rename     - Add _merged suffix to duplicate IDs

    \b
    Example:
        geocorpus merge shared/glacier_v1.tar.gz -p ./my_project
        geocorpus merge ../team_b_project/ -p ./my_project --strategy overwrite
    """
    stats = merge_into_project(Path(project_path), Path(source), strategy)
    click.echo(
        f"Merged: {stats.get('corpus_added', 0)} corpus units, "
        f"{stats.get('evidence_added', 0)} evidence links | "
        f"Skipped: {stats.get('skipped', 0)} | "
        f"Overwritten: {stats.get('overwritten', 0)}"
    )
