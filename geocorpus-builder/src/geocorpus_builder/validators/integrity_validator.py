"""IntegrityValidator -- validate referential integrity between tables."""

from .result import ValidationResult


class IntegrityValidator:
    """Validates referential integrity between tables."""

    def validate_evidence_ids_exist(
        self, units: list[dict], links: list[dict]
    ) -> list[ValidationResult]:
        results = []
        evidence_ids = {link.get("evidence_id") for link in links}
        for i, unit in enumerate(units):
            for eid in unit.get("evidence_ids", []):
                if eid not in evidence_ids:
                    results.append(ValidationResult(
                        table="corpus_units", record_index=i, severity="warning",
                        rule="referential_integrity",
                        message=f"evidence_id '{eid}' not found in evidence_links",
                        field="evidence_ids",
                    ))
        return results

    def validate_corpus_ids_consistent(
        self, units: list[dict], links: list[dict]
    ) -> list[ValidationResult]:
        results = []
        corpus_ids = {unit.get("corpus_id") for unit in units}
        for i, link in enumerate(links):
            cid = link.get("corpus_id")
            if cid and cid not in corpus_ids:
                results.append(ValidationResult(
                    table="evidence_links", record_index=i, severity="warning",
                    rule="referential_integrity",
                    message=f"corpus_id '{cid}' in evidence_links not found in corpus_units",
                    field="corpus_id",
                ))
        return results
