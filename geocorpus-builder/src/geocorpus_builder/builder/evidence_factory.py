"""EvidenceFactory -- create evidence_links records from data rows."""

from typing import Optional


class EvidenceFactory:
    """Creates evidence_links records from data table rows."""

    def __init__(self, id_prefix: str = "EV"):
        self.id_prefix = id_prefix
        self._counter = 0

    def reset_counter(self) -> None:
        self._counter = 0

    def next_evidence_id(self) -> str:
        self._counter += 1
        return f"{self.id_prefix}_{self._counter:04d}"

    def create_from_row(
        self,
        corpus_id: str,
        row: dict,
        source_table: str,
        variable: str,
        statistic: str,
        unit: str = "",
        time_range: str = "",
        spatial_scale: str = "",
    ) -> dict:
        """Build a single evidence_link dict from a data row."""
        source_id = row.get("glacier_id", row.get("grid_id", row.get("region_id", "")))
        value = row.get(statistic, row.get("value", None))

        return {
            "evidence_id": self.next_evidence_id(),
            "corpus_id": corpus_id,
            "evidence_type": "statistic",
            "source_table": source_table,
            "source_id": str(source_id),
            "variable": variable,
            "statistic": statistic,
            "value": str(value) if value is not None else None,
            "unit": unit,
            "time_range": time_range,
            "spatial_scale": spatial_scale,
            "notes": "",
        }

    def create_batch(
        self,
        rows: list[dict],
        corpus_id: str,
        source_table: str,
        variable: str,
        statistic_fields: list[str],
        unit: str = "",
        time_range: str = "",
        spatial_scale: str = "",
    ) -> list[dict]:
        """Batch-create evidence_links from a list of row dicts."""
        links = []
        for row in rows:
            for stat_field in statistic_fields:
                link = self.create_from_row(
                    corpus_id=corpus_id,
                    row=row,
                    source_table=source_table,
                    variable=variable,
                    statistic=stat_field,
                    unit=unit,
                    time_range=time_range,
                    spatial_scale=spatial_scale,
                )
                links.append(link)
        return links
