"""ValidationPipeline -- run all validators and collect results."""

from .result import ValidationResult
from .schema_validator import SchemaValidator
from .integrity_validator import IntegrityValidator
from .evidence_validator import EvidenceValidator
from .cross_table_validator import CrossTableValidator


class ValidationPipeline:
    """Runs all validators on corpus data and collects findings."""

    def __init__(self):
        self.schema = SchemaValidator()
        self.integrity = IntegrityValidator()
        self.evidence = EvidenceValidator()
        self.cross_table = CrossTableValidator()

    def run(
        self,
        corpus_units: list[dict],
        evidence_links: list[dict],
        qa_pairs: list[dict] | None = None,
        variable_dict: list[dict] | None = None,
    ) -> list[ValidationResult]:
        """Run all validators and return combined results."""
        results: list[ValidationResult] = []

        # Schema validation
        results.extend(self.schema.validate_corpus_units(corpus_units))
        results.extend(self.schema.validate_evidence_links(evidence_links))
        if qa_pairs:
            results.extend(self.schema.validate_qa_pairs(qa_pairs))

        # Integrity validation
        results.extend(self.integrity.validate_evidence_ids_exist(corpus_units, evidence_links))
        results.extend(self.integrity.validate_corpus_ids_consistent(corpus_units, evidence_links))

        # Evidence validation
        results.extend(self.evidence.validate_result_has_evidence(corpus_units, evidence_links))
        results.extend(self.evidence.validate_evidence_is_traceable(evidence_links))

        # Cross-table validation
        if variable_dict:
            results.extend(
                self.cross_table.validate_variables_in_dictionary(corpus_units, variable_dict)
            )
            results.extend(
                self.cross_table.validate_evidence_variables_in_dictionary(evidence_links, variable_dict)
            )

        return results

    def summary(self, results: list[ValidationResult]) -> dict:
        """Return a summary dict of validation results."""
        errors = [r for r in results if r.severity == "error"]
        warnings = [r for r in results if r.severity == "warning"]
        infos = [r for r in results if r.severity == "info"]
        return {
            "total": len(results),
            "errors": len(errors),
            "warnings": len(warnings),
            "info": len(infos),
            "passed": len(errors) == 0,
        }
