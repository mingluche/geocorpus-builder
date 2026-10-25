"""EvidenceValidator -- check evidence chain completeness."""

from .result import ValidationResult


class EvidenceValidator:
    """Checks that every result claim has traceable evidence."""

    def validate_result_has_evidence(
        self, units: list[dict], links: list[dict]
    ) -> list[ValidationResult]:
        results = []
        evidence_ids = {link.get("evidence_id") for link in links}
        for i, unit in enumerate(units):
            text_type = unit.get("text_type", "")
            claim_type = unit.get("claim_type", "")
            is_result = text_type in ("result", "result_template") or \
                        claim_type in ("descriptive", "comparative", "causal")
            if is_result and not unit.get("evidence_ids"):
                results.append(ValidationResult(
                    table="corpus_units", record_index=i, severity="warning",
                    rule="evidence_chain_empty",
                    message=f"Result corpus unit '{unit.get('corpus_id')}' has no evidence_ids",
                    field="evidence_ids",
                ))
        return results

    def validate_evidence_is_traceable(
        self, links: list[dict]
    ) -> list[ValidationResult]:
        results = []
        for i, link in enumerate(links):
            source_table = link.get("source_table", "")
            source_id = link.get("source_id", "")
            if not source_table:
                results.append(ValidationResult(
                    table="evidence_links", record_index=i, severity="error",
                    rule="evidence_untraceable",
                    message="source_table is empty, evidence cannot be traced",
                    field="source_table",
                ))
            if not source_id:
                results.append(ValidationResult(
                    table="evidence_links", record_index=i, severity="error",
                    rule="evidence_untraceable",
                    message="source_id is empty, evidence cannot be traced",
                    field="source_id",
                ))
        return results
