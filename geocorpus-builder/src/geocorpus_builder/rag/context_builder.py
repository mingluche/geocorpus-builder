"""ContextBuilder -- assemble retrieved evidence into a prompt context."""

from .retriever import RetrievedContext


class ContextBuilder:
    """Builds a structured context string from retrieved evidence."""

    def build(self, context: RetrievedContext, language: str = "zh") -> str:
        """Assemble retrieved context into a formatted string for the LLM."""
        parts = []

        if language == "zh":
            parts.append(f"## 检索到的语料单元 ({len(context.relevant_units)} 条)")
        else:
            parts.append(f"## Retrieved Corpus Units ({len(context.relevant_units)})")

        for unit in context.relevant_units[:8]:
            parts.append(
                f"- [{unit.get('corpus_id')}] {unit.get('text', '')}\n"
                f"  对象: {unit.get('geo_object_id')}, "
                f"变量: {unit.get('variable')}, "
                f"时间: {unit.get('time_range')}, "
                f"类型: {unit.get('text_type')}"
            )

        if context.relevant_evidence:
            if language == "zh":
                parts.append(f"\n## 关联证据 ({len(context.relevant_evidence)} 条)")
            else:
                parts.append(f"\n## Linked Evidence ({len(context.relevant_evidence)})")
            for ev in context.relevant_evidence[:8]:
                parts.append(
                    f"- [{ev.get('evidence_id')}] {ev.get('variable')} "
                    f"{ev.get('statistic')} = {ev.get('value')} "
                    f"{ev.get('unit', '')} "
                    f"[{ev.get('source_table')} / {ev.get('source_id')}]"
                )

        if context.relevant_concepts:
            if language == "zh":
                parts.append(f"\n## 相关概念 ({len(context.relevant_concepts)} 条)")
            else:
                parts.append(f"\n## Related Concepts ({len(context.relevant_concepts)})")
            for c in context.relevant_concepts[:5]:
                parts.append(f"- {c.get('zh')} ({c.get('en')}): {c.get('definition')}")

        if context.missing_tables:
            if language == "zh":
                parts.append(f"\n## 缺失的数据表: {', '.join(context.missing_tables)}")
            else:
                parts.append(f"\n## Missing Tables: {', '.join(context.missing_tables)}")

        return "\n".join(parts)
