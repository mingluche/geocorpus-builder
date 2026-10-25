"""System prompt loading and message builders for the RAG agent."""

from importlib import resources
from pathlib import Path


def load_system_prompt() -> str:
    """Load the bundled geocorpus_agent_system_prompt.md, or a custom path."""
    try:
        data_ref = resources.files("geocorpus_builder.data")
        prompt_file = data_ref.joinpath("geocorpus_agent_system_prompt.md")
        if prompt_file.is_file():
            return prompt_file.read_text(encoding="utf-8")
    except Exception:
        pass
    return _default_system_prompt()


def load_system_prompt_from_project(project_root: Path) -> str:
    """Load system prompt from a project's data directory, fallback to bundled."""
    local = project_root / "data" / "geocorpus_agent_system_prompt.md"
    if local.exists():
        return local.read_text(encoding="utf-8")
    return load_system_prompt()


def build_answer_instruction(language: str = "zh") -> str:
    """Build the answer formatting instruction."""
    if language == "zh":
        return (
            "请根据上面的证据回答用户的问题。\n"
            "如果证据充足，回答时需包含：对象ID、变量、时间范围、统计量和单位、证据来源。\n"
            "如果证据不足，请说明：当前语料库缺少该问题所需的证据表/字段：...\n"
            "使用清晰的中文回答。"
        )
    else:
        return (
            "Answer the user's question based on the evidence above.\n"
            "If evidence is sufficient, include: object ID, variable, time range, statistic and unit, evidence source.\n"
            "If evidence is insufficient, state which tables/fields are missing.\n"
            "Answer in clear English."
        )


def _default_system_prompt() -> str:
    return """# GeoCorpus Agent System Prompt

You are a geographically grounded Earth-science corpus agent.

## Core principles
1. Link every scientific statement to geo_object_id, variable, time_range, spatial_scale, and evidence_ids.
2. Do not invent data values. If a value is not present, identify which table is needed.
3. Separate definition, method, result, interpretation, and uncertainty.
4. Preserve geographical meaning. Distinguish GeoObject, GeoField, GeoRegion, GeoEvent, and GeoRelation.

## Answer rules
1. Identify the question type.
2. Check required tables and evidence.
3. Cite evidence IDs, variables, time ranges, and units.
4. When evidence is missing, state what is missing.

Use clear scientific Chinese unless the user asks for English.
"""
