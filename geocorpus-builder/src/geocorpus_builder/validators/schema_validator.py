"""SchemaValidator -- validate field types, required fields, and enum values."""

from .result import ValidationResult


class SchemaValidator:
    """Validate field existence, types, enum values, required fields."""

    def validate_corpus_units(self, units: list[dict]) -> list[ValidationResult]:
        results = []
        required = ["corpus_id", "text", "text_type", "domain",
                     "geo_object_id", "variable", "time_range"]
        for i, unit in enumerate(units):
            for field in required:
                if field not in unit or unit[field] is None:
                    results.append(ValidationResult(
                        table="corpus_units", record_index=i, severity="error",
                        rule="field_required",
                        message=f"Required field '{field}' is missing or null",
                        field=field,
                    ))
            cid = unit.get("corpus_id", "")
            if not str(cid).startswith("GC_"):
                results.append(ValidationResult(
                    table="corpus_units", record_index=i, severity="error",
                    rule="id_pattern", message=f"corpus_id '{cid}' must start with 'GC_'",
                    field="corpus_id",
                ))
            if not unit.get("text", "").strip():
                results.append(ValidationResult(
                    table="corpus_units", record_index=i, severity="error",
                    rule="field_required", message="text must not be empty",
                    field="text",
                ))
            if not unit.get("geo_object_id", "").strip():
                results.append(ValidationResult(
                    table="corpus_units", record_index=i, severity="error",
                    rule="field_required", message="geo_object_id must not be empty",
                    field="geo_object_id",
                ))
            if not unit.get("variable", "").strip():
                results.append(ValidationResult(
                    table="corpus_units", record_index=i, severity="error",
                    rule="field_required", message="variable must not be empty",
                    field="variable",
                ))
            evidence_ids = unit.get("evidence_ids", [])
            if not isinstance(evidence_ids, list):
                results.append(ValidationResult(
                    table="corpus_units", record_index=i, severity="error",
                    rule="type_error", message="evidence_ids must be a list",
                    field="evidence_ids",
                ))
        return results

    def validate_evidence_links(self, links: list[dict]) -> list[ValidationResult]:
        results = []
        required = ["evidence_id", "evidence_type", "source_table", "source_id",
                     "variable", "statistic"]
        for i, link in enumerate(links):
            for field in required:
                if field not in link or link[field] is None:
                    results.append(ValidationResult(
                        table="evidence_links", record_index=i, severity="error",
                        rule="field_required",
                        message=f"Required field '{field}' is missing or null",
                        field=field,
                    ))
            eid = link.get("evidence_id", "")
            if not str(eid).startswith("EV_"):
                results.append(ValidationResult(
                    table="evidence_links", record_index=i, severity="error",
                    rule="id_pattern", message=f"evidence_id '{eid}' must start with 'EV_'",
                    field="evidence_id",
                ))
        return results

    def validate_qa_pairs(self, pairs: list[dict]) -> list[ValidationResult]:
        results = []
        required = ["qa_id", "question", "answer", "domain"]
        for i, pair in enumerate(pairs):
            for field in required:
                if field not in pair or pair[field] is None:
                    results.append(ValidationResult(
                        table="qa_pairs", record_index=i, severity="error",
                        rule="field_required",
                        message=f"Required field '{field}' is missing or null",
                        field=field,
                    ))
            qid = pair.get("qa_id", "")
            if not str(qid).startswith("QA_"):
                results.append(ValidationResult(
                    table="qa_pairs", record_index=i, severity="error",
                    rule="id_pattern", message=f"qa_id '{qid}' must start with 'QA_'",
                    field="qa_id",
                ))
        return results
