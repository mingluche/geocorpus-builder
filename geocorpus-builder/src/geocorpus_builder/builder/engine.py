"""BuildOrchestrator -- corpus generation engine."""

from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

import pandas as pd

from ..config.project import GeoCorpusProject
from ..io import read_table
from .templates import TemplateRenderer
from .evidence_factory import EvidenceFactory


@dataclass
class BuildReport:
    units_created: int = 0
    evidence_created: int = 0
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


@dataclass
class BuildStep:
    """A single step in a build pipeline: table -> corpus units + evidence."""

    table: str
    template: str
    text_type: str = "result"
    domain: str = "cryosphere"
    subdomain: str = "glacier"
    geo_object_type: str = "glacier"
    geo_object_id_field: str = "glacier_id"
    spatial_scale: str = "object"
    variable: str = ""
    claim_type: str = "descriptive"
    statistic_fields: list[str] = field(default_factory=lambda: ["mean"])
    unit: str = "m"
    time_range: str = ""
    confidence: str = "medium"
    source: str = "script_generated"
    multi_var_cols: list[str] = field(default_factory=list)  # columns that ARE variables (not statistics)


class BuildOrchestrator:
    """Orchestrates corpus unit generation from data tables."""

    def __init__(self, project: GeoCorpusProject):
        self.project = project
        self.settings = project.config
        self.renderer = TemplateRenderer(project.root / project.config.templates_dir)
        self.evidence_factory = EvidenceFactory()

    def build(self,
              tables: dict[str, Path] | None = None,
              output: Path | None = None,
              spatial_enrich: bool = False,
              id_prefix: str = "GC_BUILT") -> BuildReport:
        """Run the build pipeline."""
        report = BuildReport()
        steps = self._get_steps()

        if tables is None:
            tables = self._discover_tables()

        all_units: list[dict] = []
        all_evidence: list[dict] = []

        for step in steps:
            if step.table not in tables:
                report.warnings.append(f"Table '{step.table}' not found, skipping")
                continue

            try:
                df = read_table(tables[step.table])
                rows = df.to_dict(orient="records")
            except Exception as e:
                report.errors.append(f"Failed to read table '{step.table}': {e}")
                continue

            for row in rows:
                geo_object_id = row.get(step.geo_object_id_field, "")
                if not geo_object_id:
                    continue

                time_range = step.time_range or row.get("time_range", "unknown")
                row_variable = step.variable or row.get("variable", "unknown")

                # Multi-variable mode: each column IS a variable (e.g. population, gdp)
                if step.multi_var_cols:
                    iter_fields = step.multi_var_cols
                    is_multi_var = True
                else:
                    iter_fields = step.statistic_fields
                    is_multi_var = False

                for field in iter_fields:
                    value = row.get(field)
                    if value is None:
                        continue

                    if is_multi_var:
                        variable = field
                        statistic = "value"
                        actual_unit = ""
                    else:
                        variable = row_variable
                        statistic = field
                        actual_unit = step.unit

                    corpus_id = self._next_corpus_id(step, all_units, id_prefix)
                    context = {
                        **row,
                        "glacier_id": geo_object_id,
                        "geo_object_id": geo_object_id,
                        "variable": variable,
                        "value": value,
                        "statistic": statistic,
                        "time_range": time_range,
                        "source_table": step.table,
                        "unit": actual_unit,
                    }

                    text = self.renderer.render(step.template, context)

                    unit = {
                        "corpus_id": corpus_id,
                        "text": text,
                        "text_type": step.text_type,
                        "domain": step.domain,
                        "subdomain": step.subdomain,
                        "geo_object_type": step.geo_object_type,
                        "geo_object_id": str(geo_object_id),
                        "spatial_scale": step.spatial_scale,
                        "time_range": time_range,
                        "variable": variable,
                        "claim_type": step.claim_type,
                        "evidence_ids": [],
                        "confidence": step.confidence,
                        "source": step.source,
                    }
                    # Carry coordinate fields for spatial enrichment
                    for coord_field in ("lon", "lat", "longitude", "latitude"):
                        if coord_field in row:
                            unit[coord_field] = row[coord_field]
                    all_units.append(unit)

                    evidence = self.evidence_factory.create_batch(
                        rows=[row],
                        corpus_id=corpus_id,
                        source_table=step.table,
                        variable=variable,
                        statistic_fields=[field],
                        unit=actual_unit,
                        time_range=time_range,
                        spatial_scale=step.spatial_scale,
                    )
                    for ev in evidence:
                        unit["evidence_ids"].append(ev["evidence_id"])
                    all_evidence.extend(evidence)

        # Spatial enrichment: add region info to each corpus unit
        if spatial_enrich:
            enriched_evidence = self._apply_spatial_enrich(all_units)
            if enriched_evidence:
                all_evidence.extend(enriched_evidence)
                report.evidence_created += len(enriched_evidence)

        # Post-build enrichment: generate interpretation/comparison/method units
        enriched = self._post_build_enrich(all_units, all_evidence, steps, id_prefix)
        if enriched:
            all_units.extend(enriched)
            report.units_created += len(enriched)

        # Write output
        output_dir = output or self.project.root
        output_dir = Path(output_dir)

        # Ensure directories exist
        (output_dir / "corpus").mkdir(parents=True, exist_ok=True)
        (output_dir / "evidence").mkdir(parents=True, exist_ok=True)

        from ..io import write_jsonl, read_jsonl
        units_path = output_dir / "corpus" / "corpus_units.jsonl"
        evidence_path = output_dir / "evidence" / "evidence_links.jsonl"

        # Merge with existing data (don't overwrite previous builds)
        existing_units = []
        existing_evidence = []
        if units_path.exists():
            existing_units = read_jsonl(units_path)
        if evidence_path.exists():
            existing_evidence = read_jsonl(evidence_path)

        # Deduplicate by corpus_id
        existing_ids = {u["corpus_id"] for u in existing_units}
        new_only = [u for u in all_units if u["corpus_id"] not in existing_ids]
        merged_units = existing_units + new_only
        write_jsonl(merged_units, units_path)

        # Deduplicate evidence by evidence_id
        existing_ev_ids = {e["evidence_id"] for e in existing_evidence}
        new_ev_only = [e for e in all_evidence if e["evidence_id"] not in existing_ev_ids]
        merged_evidence = existing_evidence + new_ev_only
        write_jsonl(merged_evidence, evidence_path)

        report.units_created = len(new_only)
        report.evidence_created = len(new_ev_only)

        print(f"Build complete: {report.units_created} new corpus units, "
              f"{report.evidence_created} new evidence links")
        print(f"  Written to: {units_path} ({units_path.stat().st_size} bytes)")
        print(f"  Written to: {evidence_path} ({evidence_path.stat().st_size} bytes)")
        if report.warnings:
            for w in report.warnings:
                print(f"  Warning: {w}")
        if report.errors:
            for e in report.errors:
                print(f"  Error: {e}")

        return report

    def _apply_spatial_enrich(self, units: list[dict]) -> list[dict]:
        """Apply spatial enrichment: return evidence links for region assignments."""
        try:
            from ..spatial import SpatialQueryEngine
            engine = SpatialQueryEngine()
        except ImportError:
            print("  [spatial] geopandas not installed, skipping enrichment")
            return []

        layers = engine.list_layers()
        if not layers:
            print("  [spatial] No spatial layers installed, skipping enrichment")
            return []

        new_evidence: list[dict] = []
        for unit in units:
            geo_id = unit.get("geo_object_id", "")
            if not geo_id:
                continue

            lon = unit.get("lon")
            lat = unit.get("lat")
            if lon is None or lat is None:
                continue

            region_info = engine.locate(float(lon), float(lat))
            for lid, info in region_info.items():
                name = info.get("name_zh", info.get(lid, ""))
                rid = info.get("adcode", info.get("id", ""))

                ev_id = f"EV_SPATIAL_{len(new_evidence) + 1:04d}"
                ev = {
                    "evidence_id": ev_id,
                    "corpus_id": unit["corpus_id"],
                    "evidence_type": "crosswalk",
                    "source_table": lid,
                    "source_id": str(rid),
                    "variable": "spatial_region",
                    "statistic": "contains",
                    "value": str(name),
                    "unit": None,
                    "time_range": "static",
                    "spatial_scale": "region",
                    "notes": f"Auto-enriched: object {geo_id} belongs to {name}",
                }
                unit.setdefault("spatial_regions", {})[lid] = {"id": rid, "name": name}
                unit["evidence_ids"].append(ev_id)
                new_evidence.append(ev)

        if new_evidence:
            print(f"  [spatial] Enriched {len(new_evidence)} region assignments across "
                  f"{len(layers)} spatial layers")
        return new_evidence

    def _get_steps(self) -> list[BuildStep]:
        """Get build steps: try named profiles first, fall back to auto-detect."""
        profile = self.settings.build_profile
        if profile == "glacier":
            steps = self._glacier_steps()
            if steps:
                return steps
        return self._auto_steps()

    def _post_build_enrich(self, units: list[dict], evidence: list[dict],
                            steps: list[BuildStep], id_prefix: str) -> list[dict]:
        """Post-build: generate interpretation, comparison, and method units."""
        new_units: list[dict] = []
        evidence_by_id: dict[str, dict] = {e["evidence_id"]: e for e in evidence}

        # Group existing units by geo_object_id + variable
        from collections import defaultdict
        groups: dict[tuple, list[dict]] = defaultdict(list)
        for u in units:
            key = (u.get("geo_object_id", ""), u.get("variable", ""))
            groups[key].append(u)

        # ── 1. Multi-year trend interpretation per object ──
        for (gid, var), group in groups.items():
            if len(group) < 2:
                continue
            # Sort by time_range
            sorted_g = sorted(group, key=lambda u: u.get("time_range", ""))
            times = [u.get("time_range", "") for u in sorted_g if u.get("time_range", "")]
            if len(set(times)) < 2:
                continue

            # Get mean values for first and last period
            first = sorted_g[0]
            last = sorted_g[-1]
            for stat in ["mean", "median"]:
                val_first = None
                val_last = None
                for u in sorted_g:
                    for eid in u.get("evidence_ids", []):
                        ev = evidence_by_id.get(eid)
                        if ev and ev.get("statistic") == stat and ev.get("value"):
                            if u == first:
                                val_first = float(ev["value"])
                            if u == last:
                                val_last = float(ev["value"])
                if val_first is not None and val_last is not None and val_first != val_last:
                    change = round(val_last - val_first, 2)
                    direction = "下降" if change < 0 else "上升"
                    unit_str = first.get("unit", evidence[0].get("unit", "")) if evidence else ""
                    cid = f"{id_prefix}_INTERPRET_{len(new_units)+1:04d}"
                    text = self.renderer.render("interpret_trend", {
                        "geo_object_id": gid, "variable": var,
                        "time_range": f"{times[0]}-{times[-1]}",
                        "direction": direction,
                        "start_value": val_first, "end_value": val_last,
                        "change_value": abs(change), "unit": unit_str,
                    })
                    new_units.append({
                        "corpus_id": cid, "text": text, "text_type": "interpretation",
                        "domain": first.get("domain", ""), "subdomain": first.get("subdomain", ""),
                        "geo_object_type": first.get("geo_object_type", ""),
                        "geo_object_id": gid, "spatial_scale": "object",
                        "time_range": f"{times[0]}-{times[-1]}",
                        "variable": var, "claim_type": "descriptive",
                        "evidence_ids": [first.get("evidence_ids", [None])[0],
                                         last.get("evidence_ids", [None])[0]],
                        "confidence": "medium", "source": "script_generated",
                    })
                    break  # only one stat per pair

        # ── 2. Cross-object comparison ──
        obj_ids = list(groups.keys())
        for i in range(len(obj_ids)):
            for j in range(i + 1, min(i + 4, len(obj_ids))):
                gid_a, var_a = obj_ids[i]
                gid_b, var_b = obj_ids[j]
                if var_a != var_b:
                    continue
                group_a = groups[(gid_a, var_a)]
                group_b = groups[(gid_b, var_b)]
                # Compare mean values for same time_range
                for ua in group_a:
                    for ub in group_b:
                        if ua.get("time_range") != ub.get("time_range"):
                            continue
                        va_mean = None; vb_mean = None
                        for eid in ua.get("evidence_ids", []):
                            ev = evidence_by_id.get(eid)
                            if ev and ev.get("statistic") == "mean" and ev.get("value"):
                                va_mean = float(ev["value"])
                                break
                        for eid in ub.get("evidence_ids", []):
                            ev = evidence_by_id.get(eid)
                            if ev and ev.get("statistic") == "mean" and ev.get("value"):
                                vb_mean = float(ev["value"])
                                break
                        if va_mean is not None and vb_mean is not None:
                            diff = round(abs(va_mean - vb_mean), 2)
                            diff_pct = round(diff / max(abs(va_mean), abs(vb_mean)) * 100, 1)
                            relation = "高于" if va_mean > vb_mean else "低于"
                            cid = f"{id_prefix}_COMPARE_{len(new_units)+1:04d}"
                            text = self.renderer.render("compare_two_objects", {
                                "geo_a": gid_a, "geo_b": gid_b, "variable": var_a,
                                "statistic": "mean", "time_range": ua.get("time_range", ""),
                                "value_a": va_mean, "value_b": vb_mean,
                                "relation": relation, "diff": diff, "diff_pct": diff_pct,
                                "unit": evidence[0].get("unit", "") if evidence else "",
                            })
                            new_units.append({
                                "corpus_id": cid, "text": text, "text_type": "interpretation",
                                "domain": ua.get("domain", ""), "subdomain": ua.get("subdomain", ""),
                                "geo_object_type": "multi_object",
                                "geo_object_id": f"{gid_a},{gid_b}",
                                "spatial_scale": "region", "time_range": ua.get("time_range", ""),
                                "variable": var_a, "claim_type": "comparative",
                                "evidence_ids": ua.get("evidence_ids", [])[:1] + ub.get("evidence_ids", [])[:1],
                                "confidence": "medium", "source": "script_generated",
                            })
                        break  # one comparison per pair
                break  # limit to one pair per outer iteration

        # ── 3. Heterogeneity interpretation (from std/cv) ──
        for (gid, var), group in groups.items():
            for u in group:
                cv_val = None; std_val = None
                for eid in u.get("evidence_ids", []):
                    ev = evidence_by_id.get(eid)
                    if ev:
                        if ev.get("statistic") == "cv":
                            cv_val = ev.get("value")
                        if ev.get("statistic") == "std":
                            std_val = f"{ev.get('value','')}{ev.get('unit','')}"
                if cv_val is not None:
                    cv_f = float(cv_val)
                    interp = "异质性较低" if cv_f < 0.1 else ("中等异质性" if cv_f < 0.3 else "异质性较高")
                    cid = f"{id_prefix}_HETEROG_{len(new_units)+1:04d}"
                    text = self.renderer.render("interpret_heterogeneity", {
                        "geo_object_id": gid, "variable": var,
                        "time_range": u.get("time_range", ""),
                        "cv": cv_val, "std": std_val or "?",
                        "cv_interpretation": interp, "unit": evidence[0].get("unit", "") if evidence else "",
                    })
                    new_units.append({
                        "corpus_id": cid, "text": text, "text_type": "interpretation",
                        "domain": u.get("domain", ""), "subdomain": u.get("subdomain", ""),
                        "geo_object_type": u.get("geo_object_type", ""),
                        "geo_object_id": gid, "spatial_scale": "within_object",
                        "time_range": u.get("time_range", ""),
                        "variable": var, "claim_type": "methodological",
                        "evidence_ids": [eid],
                        "confidence": "medium", "source": "script_generated",
                    })
                    break  # one heterogeneity unit per group

        # ── 4. Cross-variable correlation per object ──
        # Group evidence by geo_object_id, find pairs of different variables
        from itertools import combinations
        from collections import defaultdict
        obj_vars: dict[str, dict[str, list[float]]] = defaultdict(lambda: defaultdict(list))
        for u in units:
            gid = u.get("geo_object_id", "")
            var = u.get("variable", "")
            for eid in u.get("evidence_ids", []):
                ev = evidence_by_id.get(eid)
                if ev and ev.get("value"):
                    try:
                        val = float(ev["value"])
                        obj_vars[gid][var].append(val)
                    except ValueError:
                        pass

        for gid, var_dict in obj_vars.items():
            var_list = list(var_dict.keys())
            for va, vb in combinations(var_list, 2):
                vals_a = var_dict[va]
                vals_b = var_dict[vb]
                min_len = min(len(vals_a), len(vals_b))
                if min_len < 3:
                    continue
                # Simple Pearson correlation
                import math
                a = vals_a[:min_len]; b = vals_b[:min_len]
                ma = sum(a) / min_len; mb = sum(b) / min_len
                sa = math.sqrt(sum((x-ma)**2 for x in a) / min_len)
                sb = math.sqrt(sum((x-mb)**2 for x in b) / min_len)
                if sa == 0 or sb == 0:
                    continue
                r = sum((a[i]-ma)*(b[i]-mb) for i in range(min_len)) / (min_len * sa * sb)
                if abs(r) < 0.5:
                    continue

                direction = "正" if r > 0 else "负"
                strength = "强" if abs(r) > 0.7 else "中等"
                if direction == "正" and r > 0.7:
                    interp = f"两个变量呈{strength}正相关，可能存在协同变化"
                elif direction == "正":
                    interp = f"两个变量呈{strength}正相关"
                elif r < -0.7:
                    interp = f"两个变量呈{strength}负相关，可能存在此消彼长关系"
                else:
                    interp = f"两个变量呈{strength}负相关"

                cid = f"{id_prefix}_CROSSVAR_{len(new_units)+1:04d}"
                time_range = units[0].get("time_range", "") if units else ""
                text = self.renderer.render("cross_var_correlation", {
                    "geo_object_id": gid, "var_a": va, "var_b": vb,
                    "time_range": time_range,
                    "correlation_direction": direction, "correlation_r": round(r, 3),
                    "interpretation": interp,
                    "source_table": "cross_variable_analysis",
                })
                new_units.append({
                    "corpus_id": cid, "text": text, "text_type": "interpretation",
                    "domain": units[0].get("domain", ""), "subdomain": "cross_variable",
                    "geo_object_type": "multi_variable",
                    "geo_object_id": gid, "spatial_scale": "object",
                    "time_range": time_range, "variable": f"{va}_vs_{vb}",
                    "claim_type": "causal", "evidence_ids": [],
                    "confidence": "medium", "source": "script_generated",
                })

        if new_units:
            print(f"  [enrich] Generated {len(new_units)} additional units "
                  f"(interpretation/comparison/heterogeneity/cross-var)")
        return new_units

    def _auto_steps(self) -> list[BuildStep]:
        """Auto-detect build steps from discovered tables.

        For each CSV/Parquet in statistics/, inspects columns to infer
        geo_object_type, variable, and statistic fields.
        """
        tables = self._discover_tables()
        if not tables:
            return []

        steps = []
        for table_name, table_path in tables.items():
            try:
                df = read_table(table_path)
                cols = list(df.columns)
            except Exception:
                continue

            # Infer geo type from columns
            if "glacier_id" in cols:
                geo_type = "glacier"
                geo_id_field = "glacier_id"
            elif "region_id" in cols:
                geo_type = "region"
                geo_id_field = "region_id"
            elif "grid_id" in cols:
                geo_type = "grid"
                geo_id_field = "grid_id"
            else:
                geo_type = "object"
                geo_id_field = cols[0]

            # Infer variable from column content
            variable = ""
            if "variable" in cols:
                variable = str(df["variable"].iloc[0]) if len(df) > 0 else ""
            if not variable:
                variable = table_name

            # Infer statistic columns vs multi-variable columns
            exclude = {geo_id_field, "year", "variable", "time_range",
                       "lon", "lat", "longitude", "latitude", "geometry"}
            num_cols = [c for c in cols if c not in exclude
                        and df[c].dtype in ("float64", "int64", "float32", "int32")]

            # Heuristic: if columns look like variable names (not stat names),
            # treat each as a separate variable with 'value' as the statistic
            stat_names = {"mean", "median", "std", "min", "max", "count", "sum",
                          "p10", "p25", "p75", "p90", "cv", "variance"}
            var_like = [c for c in num_cols if c.lower() not in stat_names]
            stat_like = [c for c in num_cols if c.lower() in stat_names]

            if var_like and not stat_like:
                # Multi-variable mode: each column is a variable
                stat_cols = var_like
                actual_var_like = var_like
            else:
                # Single-variable mode: columns are statistics
                stat_cols = stat_like if stat_like else num_cols
                actual_var_like = []

            # Detect time_range
            time_range = ""
            if "time_range" in cols and len(df) > 0:
                time_range = str(df["time_range"].iloc[0])
            if not time_range and "year" in cols:
                years = sorted(df["year"].unique())
                if len(years) == 1:
                    time_range = str(years[0])
                elif len(years) >= 2:
                    time_range = f"{years[0]}-{years[-1]}"

            # Detect domain from variable
            domain = "cryosphere"
            if any(k in variable.lower() for k in ("elevation", "dem", "slope")):
                domain = "geomorphology"
            elif any(k in variable.lower() for k in ("precip", "temp", "climate")):
                domain = "climatology"

            # Choose template: generic_change if variable suggests change/trend, else generic_stat
            template = "generic_stat"
            if any(k in variable.lower() for k in ("change", "trend", "rate", "diff", "变")):
                template = "generic_change"

            step = BuildStep(
                table=table_name,
                template=template,
                text_type="result",
                domain=domain,
                subdomain=table_name.split("_")[0] if "_" in table_name else "",
                geo_object_type=geo_type,
                geo_object_id_field=geo_id_field,
                spatial_scale="object",
                variable=variable,
                claim_type="descriptive",
                statistic_fields=stat_cols if not actual_var_like else ["value"],
                multi_var_cols=actual_var_like,
                unit="",
                time_range=time_range,
                confidence="medium",
                source="script_generated",
            )
            steps.append(step)

        return steps

    def _glacier_steps(self) -> list[BuildStep]:
        """Return glacier build steps only if required tables exist."""
        tables = self._discover_tables()
        if "glacier_yearly_stats" not in tables and "glacier_change_stats" not in tables:
            return []  # fall back to auto
        return [
            BuildStep(
                table="glacier_yearly_stats",
                template="glacier_yearly_thickness",
                text_type="result",
                geo_object_type="glacier",
                geo_object_id_field="glacier_id",
                spatial_scale="object",
                variable="glacier_thickness",
                claim_type="descriptive",
                statistic_fields=["mean", "median"],
                unit="m",
            ),
            BuildStep(
                table="glacier_change_stats",
                template="glacier_thickness_change",
                text_type="result",
                geo_object_type="glacier",
                geo_object_id_field="glacier_id",
                spatial_scale="object",
                variable="glacier_thickness_change",
                claim_type="descriptive",
                statistic_fields=["mean_change"],
                unit="m",
                time_range="2017-2024",
            ),
        ]

    def _discover_tables(self) -> dict[str, Path]:
        tables = {}
        stats_dir = self.project.root / "statistics"
        if stats_dir.exists():
            for f in stats_dir.glob("*.parquet"):
                tables[f.stem] = f
            for f in stats_dir.glob("*.csv"):
                tables[f.stem] = f
        return tables

    @staticmethod
    def _next_corpus_id(step: BuildStep, existing: list[dict], prefix: str = "GC_BUILT") -> str:
        count = len(existing) + 1
        return f"{prefix}_{step.subdomain.upper()}_{count:04d}"
