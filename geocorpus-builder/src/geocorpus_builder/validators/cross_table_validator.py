"""CrossTableValidator -- validate consistency across tables."""

from .result import ValidationResult


class CrossTableValidator:
    """Validates consistency between different tables."""

    def validate_variables_in_dictionary(
        self, units: list[dict], var_dict: list[dict]
    ) -> list[ValidationResult]:
        results = []
        var_ids = {v.get("variable_id") for v in var_dict}
        for i, unit in enumerate(units):
            variable = unit.get("variable", "")
            if variable and variable not in var_ids:
                results.append(ValidationResult(
                    table="corpus_units", record_index=i, severity="warning",
                    rule="variable_not_in_dictionary",
                    message=f"Variable '{variable}' not found in variable_dictionary",
                    field="variable",
                ))
        return results

    def validate_evidence_variables_in_dictionary(
        self, links: list[dict], var_dict: list[dict]
    ) -> list[ValidationResult]:
        results = []
        var_ids = {v.get("variable_id") for v in var_dict}
        for i, link in enumerate(links):
            variable = link.get("variable", "")
            if variable and variable not in var_ids:
                results.append(ValidationResult(
                    table="evidence_links", record_index=i, severity="warning",
                    rule="variable_not_in_dictionary",
                    message=f"Variable '{variable}' not found in variable_dictionary",
                    field="variable",
                ))
        return results
