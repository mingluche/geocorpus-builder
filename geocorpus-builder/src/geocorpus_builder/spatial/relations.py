"""SpatialRelations -- precompute and export spatial relationships as evidence_links."""

from __future__ import annotations

from pathlib import Path
from typing import Optional

import geopandas as gpd

from .engine import SpatialQueryEngine


class SpatialRelations:
    """Build and export spatial relationships: adjacency, containment, overlap weights.

    Results can be exported as evidence_links JSONL for integration with the GeoCorpus.
    """

    def __init__(self, engine: SpatialQueryEngine):
        self.engine = engine

    def build_adjacency_table(self, layer: str) -> list[dict]:
        """Build adjacency pairs for all regions in a layer.

        Returns: [{source_id, target_id, relation_type: "adjacent", layer_id}, ...]
        """
        meta = self.engine.registry.get_layer(layer)
        gdf = self.engine._load_layer(layer)
        if gdf is None or meta is None:
            return []

        id_field = meta.id_field
        name_field = meta.name_field
        results: list[dict] = []

        for i, row_i in gdf.iterrows():
            geom_i = row_i.geometry
            sid = str(row_i[id_field])
            for j, row_j in gdf.iterrows():
                if j <= i:
                    continue
                if geom_i.touches(row_j.geometry):
                    tid = str(row_j[id_field])
                    results.append({
                        "source_id": sid,
                        "source_name": str(row_i.get(name_field, "")),
                        "target_id": tid,
                        "target_name": str(row_j.get(name_field, "")),
                        "relation_type": "adjacent",
                        "layer_id": layer,
                        "layer_name": meta.layer_name,
                    })

        return results

    def build_containment_table(self, child_layer: str, parent_layer: str) -> list[dict]:
        """Build containment relations: which parent region contains each child.

        Uses centroid-based containment (fast approximation).
        """
        child_gdf = self.engine._load_layer(child_layer)
        parent_gdf = self.engine._load_layer(parent_layer)
        child_meta = self.engine.registry.get_layer(child_layer)
        parent_meta = self.engine.registry.get_layer(parent_layer)

        if child_gdf is None or parent_gdf is None or child_meta is None or parent_meta is None:
            return []

        results: list[dict] = []
        child_id_field = child_meta.id_field
        parent_id_field = parent_meta.id_field

        for _, crow in child_gdf.iterrows():
            centroid = crow.geometry.centroid
            for _, prow in parent_gdf.iterrows():
                if prow.geometry.contains(centroid):
                    results.append({
                        "child_id": str(crow[child_id_field]),
                        "child_name": str(crow.get(child_meta.name_field, "")),
                        "parent_id": str(prow[parent_id_field]),
                        "parent_name": str(prow.get(parent_meta.name_field, "")),
                        "relation_type": "contained_by",
                        "child_layer": child_layer,
                        "parent_layer": parent_layer,
                    })
                    break

        return results

    def build_overlap_table(self,
                            source_geometries: list[dict],
                            target_layer: str,
                            source_id_field: str = "id") -> list[dict]:
        """Calculate overlap weights between source geometries and a target layer.

        source_geometries: list of {id, geometry} dicts.
        Returns: [{source_id, target_id, overlap_area_m2, area_fraction}, ...]
        """
        target_gdf = self.engine._load_layer(target_layer)
        target_meta = self.engine.registry.get_layer(target_layer)
        if target_gdf is None or target_meta is None:
            return []

        results: list[dict] = []
        for src in source_geometries:
            overlaps = self.engine.overlap(src["geometry"], target_layer)
            for ol in overlaps:
                ol["source_id"] = src[source_id_field]
            results.extend(overlaps)

        return results

    def export_as_evidence_links(self, relations: list[dict],
                                  source_table: str,
                                  output_path: Path) -> list[dict]:
        """Convert spatial relations to evidence_links format and write to JSONL."""
        import json

        evidence = []
        for i, rel in enumerate(relations):
            ev = {
                "evidence_id": f"EV_SPATIAL_{i+1:04d}",
                "corpus_id": None,
                "evidence_type": "crosswalk",
                "source_table": source_table,
                "source_id": rel.get("source_id", rel.get("child_id", "")),
                "variable": rel.get("relation_type", "spatial_relation"),
                "statistic": "definition",
                "value": json.dumps(rel, ensure_ascii=False),
                "unit": None,
                "time_range": "static",
                "spatial_scale": "region",
                "notes": f"Spatial relation: {rel.get('relation_type', '')}",
            }
            evidence.append(ev)

        output_path.parent.mkdir(parents=True, exist_ok=True)
        with open(output_path, "w", encoding="utf-8") as f:
            for ev in evidence:
                f.write(json.dumps(ev, ensure_ascii=False) + "\n")

        return evidence
