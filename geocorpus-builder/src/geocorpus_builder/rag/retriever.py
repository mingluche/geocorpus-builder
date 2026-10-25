"""EvidenceRetriever -- search corpus and evidence for relevant information."""

import re
from dataclasses import dataclass, field


def _is_cjk(ch: str) -> bool:
    cp = ord(ch)
    return (0x4E00 <= cp <= 0x9FFF or
            0x3400 <= cp <= 0x4DBF or
            0xF900 <= cp <= 0xFAFF)


@dataclass
class RetrievedContext:
    """Context retrieved from the corpus for answering a question."""

    question: str
    question_type: str = "data_query"
    relevant_units: list[dict] = field(default_factory=list)
    relevant_evidence: list[dict] = field(default_factory=list)
    relevant_concepts: list[dict] = field(default_factory=list)
    relevant_qa: list[dict] = field(default_factory=list)
    confidence: str = "medium"
    missing_tables: list[str] = field(default_factory=list)


class EvidenceRetriever:
    """Searches corpus data by keyword matching to find relevant evidence."""

    def __init__(self,
                 corpus_units: list[dict],
                 evidence_links: list[dict],
                 geo_concepts: list[dict],
                 variable_dict: list[dict],
                 qa_pairs: list[dict]):
        self.corpus_units = corpus_units
        self.evidence_links = evidence_links
        self.geo_concepts = geo_concepts
        self.variable_dict = variable_dict
        self.qa_pairs = qa_pairs

    def retrieve(self, question: str) -> RetrievedContext:
        """Retrieve relevant context for a question."""
        question_type = self._identify_question_type(question)
        keywords = self._extract_keywords(question)

        ctx = RetrievedContext(
            question=question,
            question_type=question_type,
        )

        # Search corpus units by keyword overlap
        ctx.relevant_units = self._search_corpus(keywords)
        ctx.relevant_concepts = self._search_concepts(keywords)
        ctx.relevant_qa = self._search_qa(keywords)

        # Fetch linked evidence for matching corpus units
        evidence_ids = set()
        for unit in ctx.relevant_units:
            for eid in unit.get("evidence_ids", []):
                evidence_ids.add(eid)

        evidence_map = {e["evidence_id"]: e for e in self.evidence_links}
        ctx.relevant_evidence = [evidence_map[eid] for eid in evidence_ids if eid in evidence_map]

        # Check what tables are needed but missing
        ctx.missing_tables = self._check_missing_tables(question, ctx)

        # Assess confidence
        if ctx.relevant_evidence:
            ctx.confidence = "high"
        elif ctx.relevant_units:
            ctx.confidence = "medium"
        else:
            ctx.confidence = "low"

        return ctx

    def _identify_question_type(self, question: str) -> str:
        q_lower = question.lower()
        kw_map = {
            "definition": ["是什么", "什么是", "define", "what is", "定义", "区别",
                          "是什么意思", "如何区分"],
            "data_query": ["多少", "变化", "thickness", "change", "rate", "面积",
                          "厚度", "速率", "变薄", "how much", "数值"],
            "comparison": ["比较", "对比", "compare", "difference", "差异",
                          "哪个更", "之间"],
            "method": ["如何", "怎么", "how to", "方法", "步骤", "流程",
                      "计算", "测量"],
            "result": ["结果", "result", "发现", "结论", "表明"],
            "uncertainty": ["不确定", "误差", "uncertainty", "error", "精度",
                           "变异", "异质性"],
        }
        for qtype, kws in kw_map.items():
            if any(kw in q_lower for kw in kws):
                return qtype
        return "data_query"

    def _extract_keywords(self, question: str) -> list[str]:
        """Extract search keywords from the question."""
        # Split on spaces and punctuation; CJK tokens get bigram-split
        tokens = re.split(r'[\s,，。？?！!、：:；;（）()""\'\'——–-]+', question)
        stopwords = {"的", "是", "在", "了", "和", "与", "或", "the", "is", "a", "an",
                     "of", "in", "to", "for", "什么", "如何", "怎么", "吗", "呢", "吧",
                     "what", "how", "why", "when", "where", "which", "who",
                     "是多少", "多少", "哪些", "哪个", "什么", "为什么"}
        keywords = [t for t in tokens if len(t) >= 2 and t.lower() not in stopwords]

        # For CJK tokens that are long (unsegmented), split into bigrams
        cjk_keywords = []
        for kw in keywords:
            cjk_chars = ''.join(c for c in kw if _is_cjk(c))
            if len(cjk_chars) >= 6:
                for i in range(len(cjk_chars) - 1):
                    cjk_keywords.append(cjk_chars[i:i+2])
            elif len(cjk_chars) >= 2:
                cjk_keywords.append(cjk_chars)
            alnum = re.findall(r'[a-zA-Z0-9_]+', kw)
            cjk_keywords.extend(alnum)

        return cjk_keywords

    def _search_corpus(self, keywords: list[str], top_k: int = 10,
                        spatial_filter: str = "") -> list[dict]:
        """Keyword-overlap search across corpus_units, with optional spatial filter.

        spatial_filter: "layer_id:region_id" or "layer_id:region_name" to filter by region.
        """
        candidates = self.corpus_units

        # Apply spatial filter
        if spatial_filter and ":" in spatial_filter:
            lid, r_val = spatial_filter.split(":", 1)
            filtered = []
            for unit in candidates:
                regions = unit.get("spatial_regions", {})
                if lid in regions:
                    r_info = regions[lid]
                    if r_val in (r_info.get("id", ""), r_info.get("name", "")):
                        filtered.append(unit)
            candidates = filtered

        if not keywords:
            return candidates[:top_k]

        scored = []
        for unit in candidates:
            # Search across text, variable, geo_object_id, corpus_id, and spatial region names
            search_text = " ".join([
                unit.get("text", ""),
                unit.get("variable", ""),
                unit.get("geo_object_id", ""),
                unit.get("corpus_id", ""),
            ])
            # Also include spatial region names
            for lid, info in unit.get("spatial_regions", {}).items():
                search_text += " " + info.get("name", "") + " " + info.get("id", "")
            text_lower = search_text.lower()
            score = sum(1 for kw in keywords if kw.lower() in text_lower)
            if score > 0:
                scored.append((score, unit))
        scored.sort(key=lambda x: x[0], reverse=True)
        return [unit for _, unit in scored[:top_k]]

    def _search_concepts(self, keywords: list[str]) -> list[dict]:
        results = []
        for c in self.geo_concepts:
            text = c.get("zh", "") + " " + c.get("en", "") + " " + c.get("definition", "")
            if any(kw.lower() in text.lower() for kw in keywords):
                results.append(c)
        return results

    def _search_qa(self, keywords: list[str]) -> list[dict]:
        results = []
        for qa in self.qa_pairs:
            text = qa.get("question", "") + " " + qa.get("answer", "")
            if any(kw.lower() in text.lower() for kw in keywords):
                results.append(qa)
        return results

    def _check_missing_tables(self, question: str, ctx: RetrievedContext) -> list[str]:
        """Detect which tables are needed but have no evidence."""
        missing = []
        q_lower = question.lower()
        table_hints = {
            "glacier_yearly_stats": ["yearly", "每年", "逐年", "annual", "年"],
            "glacier_change_stats": ["变化", "change", "变薄", "thinning"],
            "glacier_neighbor_index": ["邻近", "相邻", "neighbor", "距离", "distance", "空间依赖"],
            "region_summary": ["区域", "region", "区域平均"],
            "glacier_grid_crosswalk": ["网格", "grid", "像元", "pixel"],
        }
        for table, hints in table_hints.items():
            if any(h in q_lower for h in hints):
                # Check if we have evidence from this table
                has_evidence = any(
                    table in e.get("source_table", "") for e in ctx.relevant_evidence
                )
                if not has_evidence:
                    missing.append(table)
        return missing
