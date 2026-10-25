"""GeoCorpusAgent -- RAG agent that answers questions grounded in corpus evidence."""

from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from ..io import read_jsonl, read_json, read_text
from .retriever import EvidenceRetriever, RetrievedContext
from .context_builder import ContextBuilder
from .prompts import load_system_prompt, load_system_prompt_from_project, build_answer_instruction


@dataclass
class AnswerResult:
    """Result of answering a question."""

    question: str
    answer: str
    question_type: str
    confidence: str
    evidence_ids: list[str] = field(default_factory=list)
    required_tables: list[str] = field(default_factory=list)
    missing_tables: list[str] = field(default_factory=list)


class GeoCorpusAgent:
    """RAG agent that answers questions grounded in GeoCorpus evidence.

    Supports three backends:
    - "cli": Template-based answer generation (no API key needed)
    - "anthropic": Use Anthropic API for full LLM answers
    - "deepseek": Use DeepSeek API (OpenAI-compatible)
    """

    def __init__(self,
                 corpus_dir: Path,
                 llm_backend: str = "cli",
                 api_key: Optional[str] = None,
                 model: Optional[str] = None,
                 language: str = "zh"):
        self.corpus_dir = Path(corpus_dir)
        self.llm_backend = llm_backend
        self.api_key = api_key
        self.model = model or {"anthropic": "claude-sonnet-4-6",
                               "deepseek": "deepseek-chat"}.get(llm_backend, "deepseek-chat")
        self.language = language
        self.system_prompt = load_system_prompt_from_project(self.corpus_dir)
        self.corpus_units: list[dict] = []
        self.evidence_links: list[dict] = []
        self.geo_concepts: list[dict] = []
        self.variable_dict: list[dict] = []
        self.qa_pairs: list[dict] = []
        self._load_all()

    def _load_all(self) -> None:
        """Load all data files from the corpus directory."""
        self.corpus_units = self._load_jsonl_or_empty(
            self.corpus_dir / "corpus" / "corpus_units.jsonl"
        )
        self.evidence_links = self._load_jsonl_or_empty(
            self.corpus_dir / "evidence" / "evidence_links.jsonl"
        )
        self.qa_pairs = self._load_jsonl_or_empty(
            self.corpus_dir / "corpus" / "qa_pairs.jsonl"
        )

        # Load concepts and variable dictionary from data dir
        concepts_path = self.corpus_dir / "data" / "geo_concepts.json"
        if concepts_path.exists():
            data = read_json(concepts_path)
            self.geo_concepts = data.get("concepts", data) if isinstance(data, dict) else data

        var_path = self.corpus_dir / "data" / "variable_dictionary.json"
        if var_path.exists():
            data = read_json(var_path)
            self.variable_dict = data.get("variables", data) if isinstance(data, dict) else data

    def answer(self, question: str) -> AnswerResult:
        """Answer a question using evidence from the corpus."""
        retriever = EvidenceRetriever(
            self.corpus_units,
            self.evidence_links,
            self.geo_concepts,
            self.variable_dict,
            self.qa_pairs,
        )
        ctx = retriever.retrieve(question)

        if self.llm_backend == "anthropic" and self.api_key:
            answer_text = self._answer_via_anthropic(question, ctx)
        elif self.llm_backend == "deepseek" and self.api_key:
            answer_text = self._answer_via_deepseek(question, ctx)
        else:
            answer_text = self._answer_via_cli(question, ctx)

        evidence_ids = [e.get("evidence_id", "") for e in ctx.relevant_evidence]

        return AnswerResult(
            question=question,
            answer=answer_text,
            question_type=ctx.question_type,
            confidence=ctx.confidence,
            evidence_ids=evidence_ids,
            required_tables=list({e.get("source_table", "") for e in ctx.relevant_evidence}),
            missing_tables=ctx.missing_tables,
        )

    def _answer_via_cli(self, question: str, ctx: RetrievedContext) -> str:
        """Template-based answer generation without LLM API."""
        builder = ContextBuilder()
        context_str = builder.build(ctx, self.language)

        if ctx.question_type == "definition":
            return self._format_definition_answer(ctx)
        elif ctx.question_type == "method":
            return self._format_method_answer(ctx)

        return self._format_data_answer(ctx, context_str)

    def _format_definition_answer(self, ctx: RetrievedContext) -> str:
        """Format a definition-type answer."""
        parts = []
        if ctx.relevant_concepts:
            c = ctx.relevant_concepts[0]
            parts.append(f"{c.get('zh', '')}（{c.get('en', '')}）：{c.get('definition', '')}")
        elif ctx.relevant_units:
            u = ctx.relevant_units[0]
            parts.append(f"{u.get('text', '')}")
            parts.append(f"来源：{u.get('corpus_id', '')}")
        else:
            parts.append("当前语料库缺少该问题所需的概念定义。")
        return "\n".join(parts)

    def _format_method_answer(self, ctx: RetrievedContext) -> str:
        """Format a methodology answer."""
        parts = []
        if ctx.relevant_units:
            for u in ctx.relevant_units[:3]:
                parts.append(f"- {u.get('text', '')} [{u.get('corpus_id')}]")
        if ctx.relevant_qa:
            for qa in ctx.relevant_qa[:2]:
                parts.append(f"- {qa.get('answer', '')} [{qa.get('qa_id')}]")
        if not parts:
            parts.append("当前语料库中缺少该方法的具体说明。")
        return "\n".join(parts)

    def _format_data_answer(self, ctx: RetrievedContext, context_str: str) -> str:
        """Format a data-query answer."""
        parts = []

        if ctx.relevant_evidence:
            parts.append(f"根据语料库中的证据记录，找到 {len(ctx.relevant_evidence)} 条相关数据：\n")
            for ev in ctx.relevant_evidence[:8]:
                parts.append(
                    f"- {ev.get('variable')} {ev.get('statistic')} = "
                    f"{ev.get('value')} {ev.get('unit', '')} "
                    f"（对象: {ev.get('source_id')}, "
                    f"时间: {ev.get('time_range', '未知')}, "
                    f"来源: {ev.get('source_table')}, "
                    f"证据ID: {ev.get('evidence_id')}）"
                )
        elif ctx.relevant_units:
            parts.append("根据语料库文本记录：\n")
            for u in ctx.relevant_units[:5]:
                parts.append(
                    f"- [{u.get('corpus_id')}] {u.get('text', '')} "
                    f"（置信度: {u.get('confidence', 'unknown')}）"
                )
        else:
            parts.append("当前语料库缺少与该问题直接相关的数据或文本记录。")

        if ctx.missing_tables:
            parts.append(f"\n缺失的证据表/字段: {', '.join(ctx.missing_tables)}")
            parts.append(f"\n建议: 请先使用 geocorpus ingest 导入这些数据表的统计结果，再重新查询。")

        return "\n".join(parts)

    def _answer_via_anthropic(self, question: str, ctx: RetrievedContext) -> str:
        """Use Anthropic API for full LLM answer generation."""
        try:
            from anthropic import Anthropic
        except ImportError:
            return self._answer_via_cli(question, ctx) + (
                "\n\n[注: anthropic 包未安装，使用模板生成回答。安装: pip install anthropic]"
            )

        builder = ContextBuilder()
        context_str = builder.build(ctx, self.language)
        instruction = build_answer_instruction(self.language)

        prompt = (
            f"{self.system_prompt}\n\n"
            f"{context_str}\n\n"
            f"## 用户问题\n{question}\n\n"
            f"{instruction}"
        )

        client = Anthropic(api_key=self.api_key)
        message = client.messages.create(
            model=self.model,
            max_tokens=1024,
            system=self.system_prompt,
            messages=[{"role": "user", "content": prompt}],
        )
        return message.content[0].text

    def _answer_via_deepseek(self, question: str, ctx: RetrievedContext) -> str:
        """Use DeepSeek API (OpenAI-compatible) for LLM answer generation."""
        try:
            from openai import OpenAI
        except ImportError:
            return self._answer_via_cli(question, ctx) + (
                "\n\n[注: openai 包未安装，使用模板生成回答。安装: pip install openai]"
            )

        builder = ContextBuilder()
        context_str = builder.build(ctx, self.language)
        instruction = build_answer_instruction(self.language)

        client = OpenAI(
            api_key=self.api_key,
            base_url="https://api.deepseek.com",
        )
        response = client.chat.completions.create(
            model=self.model,
            max_tokens=1024,
            temperature=0.1,
            messages=[
                {"role": "system", "content": self.system_prompt},
                {"role": "user", "content": f"{context_str}\n\n## 用户问题\n{question}\n\n{instruction}"},
            ],
        )
        return response.choices[0].message.content or ""

    @staticmethod
    def _load_jsonl_or_empty(path: Path) -> list[dict]:
        if path.exists():
            return read_jsonl(path)
        return []
