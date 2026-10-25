"""geocorpus validate -- validate corpus data against the schema."""

from pathlib import Path

import click
from rich.console import Console
from rich.table import Table

from ..config.project import GeoCorpusProject
from ..io import read_jsonl, read_json
from ..validators import ValidationPipeline


@click.command()
@click.argument("target", type=click.Path(exists=True), default=".")
@click.option("--report", "-r", type=click.Choice(["table", "json", "summary"]),
              default="table", help="Report format")
@click.option("--fail-fast", is_flag=True, default=False, help="Stop on first error")
def validate(target: str, report: str, fail_fast: bool) -> None:
    """Validate corpus units and evidence links against the schema.

    TARGET can be a project directory or individual JSONL/JSON file.
    """
    target_path = Path(target).resolve()
    project = GeoCorpusProject.discover(target_path)

    # Load data
    corpus_units = _load_jsonl_or_empty(project.root / project.config.corpus_dir / "corpus_units.jsonl")
    evidence_links = _load_jsonl_or_empty(project.root / project.config.evidence_dir / "evidence_links.jsonl")
    qa_pairs = _load_jsonl_or_empty(project.root / project.config.corpus_dir / "qa_pairs.jsonl")

    var_dict = []
    var_dict_path = project.root / project.config.data_dir / "variable_dictionary.json"
    if var_dict_path.exists():
        data = read_json(var_dict_path)
        var_dict = data.get("variables", data) if isinstance(data, dict) else data

    # Run validation
    pipeline = ValidationPipeline()
    all_results = pipeline.run(corpus_units, evidence_links, qa_pairs, var_dict)

    # Filter errors if fail-fast
    if fail_fast:
        errors = [r for r in all_results if r.severity == "error"]
        if not errors:
            return
        all_results = errors

    # Output
    summary = pipeline.summary(all_results)

    if report == "summary":
        click.echo(f"Total: {summary['total']} | Errors: {summary['errors']} | "
                   f"Warnings: {summary['warnings']} | Info: {summary['info']} | "
                   f"Passed: {summary['passed']}")
    elif report == "json":
        import json
        output = [{
            "table": r.table, "record_index": r.record_index,
            "severity": r.severity, "rule": r.rule,
            "message": r.message, "field": r.field,
        } for r in all_results]
        click.echo(json.dumps(output, ensure_ascii=False, indent=2))
    else:
        _print_table(all_results, summary)

    if not summary["passed"]:
        raise SystemExit(1)


def _load_jsonl_or_empty(path: Path) -> list[dict]:
    if path.exists():
        return read_jsonl(path)
    return []


def _print_table(results, summary) -> None:
    console = Console()
    tbl = Table(title="GeoCorpus Validation Report")
    tbl.add_column("#", style="dim")
    tbl.add_column("Severity")
    tbl.add_column("Table")
    tbl.add_column("Record")
    tbl.add_column("Rule")
    tbl.add_column("Message")
    tbl.add_column("Field")

    severity_styles = {"error": "red", "warning": "yellow", "info": "blue"}

    for idx, r in enumerate(results, 1):
        style = severity_styles.get(r.severity, "")
        tbl.add_row(
            str(idx),
            f"[{style}]{r.severity}[/{style}]",
            r.table,
            str(r.record_index),
            r.rule,
            r.message,
            r.field or "-",
        )

    console.print(tbl)

    if summary["passed"]:
        console.print(f"\n[green]Validation passed: {summary['total']} checks, "
                      f"{summary['warnings']} warnings[/green]")
    else:
        console.print(f"\n[red]Validation FAILED: {summary['errors']} errors, "
                      f"{summary['warnings']} warnings[/red]")
