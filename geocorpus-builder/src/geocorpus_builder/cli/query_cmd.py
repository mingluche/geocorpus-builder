"""geocorpus query -- ask questions grounded in corpus evidence."""

from pathlib import Path

import click

from ..rag.agent import GeoCorpusAgent


@click.command()
@click.option("--project", "-p", "project_path", type=click.Path(exists=True), default=".",
              help="Path to GeoCorpus project directory")
@click.option("--question", "-q", type=str, default=None,
              help="Single question (non-interactive mode)")
@click.option("--interactive", "-i", is_flag=True, default=False,
              help="Start an interactive query session")
@click.option("--llm-backend", type=click.Choice(["cli", "anthropic", "deepseek"]),
              default="cli", help="LLM backend: cli (no key), anthropic, deepseek")
@click.option("--api-key", envvar="DEEPSEEK_API_KEY", default=None,
              help="API key (DEEPSEEK_API_KEY env var, or ANTHROPIC_API_KEY for anthropic)")
@click.option("--model", default=None, help="Model name override")
def query(project_path: str, question: str, interactive: bool,
          llm_backend: str, api_key: str | None, model: str | None) -> None:
    """Query the corpus and answer questions grounded in evidence.

    Uses evidence records from the corpus to provide data-backed answers.
    The CLI backend generates template-based answers without any API key.
    """
    proj_dir = Path(project_path).resolve()
    # Auto-detect API key from env var based on backend
    import os
    actual_key = api_key
    if not actual_key and llm_backend == "deepseek":
        actual_key = os.environ.get("DEEPSEEK_API_KEY")
    elif not actual_key and llm_backend == "anthropic":
        actual_key = os.environ.get("ANTHROPIC_API_KEY")

    agent = GeoCorpusAgent(
        corpus_dir=proj_dir,
        llm_backend=llm_backend,
        api_key=actual_key,
        model=model,
        language="zh",
    )

    if question:
        _ask_and_print(agent, question)
    elif interactive:
        _interactive_loop(agent)
    else:
        click.echo("请输入问题（-q 单次查询，-i 交互模式）：")
        q = click.prompt("> ")
        _ask_and_print(agent, q)


def _ask_and_print(agent: GeoCorpusAgent, question: str) -> None:
    """Ask a question and print the result."""
    result = agent.answer(question)

    click.echo(f"\n{'='*60}")
    click.echo(f"问题: {result.question}")
    click.echo(f"类型: {result.question_type} | 置信度: {result.confidence}")
    click.echo(f"{'='*60}")
    click.echo(f"\n{result.answer}\n")
    if result.evidence_ids:
        click.echo(f"引用证据: {', '.join(result.evidence_ids)}")
    if result.missing_tables:
        click.echo(f"缺失数据表: {', '.join(result.missing_tables)}")


def _interactive_loop(agent: GeoCorpusAgent) -> None:
    """Run an interactive query session."""
    click.echo("GeoCorpus 交互式查询 (输入 'quit' 或 'exit' 退出)")
    click.echo(f"已加载: {len(agent.corpus_units)} 条语料, "
               f"{len(agent.evidence_links)} 条证据, "
               f"{len(agent.geo_concepts)} 个概念\n")

    while True:
        try:
            q = click.prompt("查询").strip()
        except (EOFError, KeyboardInterrupt):
            click.echo("\n再见！")
            break
        if q.lower() in ("quit", "exit", "q"):
            click.echo("再见！")
            break
        if not q:
            continue
        _ask_and_print(agent, q)
