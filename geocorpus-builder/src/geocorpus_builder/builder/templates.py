"""TemplateRenderer -- render natural-language statements from data + templates."""

from pathlib import Path
from string import Template


# Generic domain-agnostic templates (used by auto-detect build)
GENERIC_TEMPLATES = {
    # ── 结果类 (descriptive result) ──
    "generic_stat": Template(
        "${time_range}年，${geo_object_id}的${variable}${statistic}为${value}${unit}"
        "（来源：${source_table}）。"
    ),
    "generic_change": Template(
        "${time_range}期间，${geo_object_id}的${variable}变化量为${value}${unit}"
        "（来源：${source_table}）。"
    ),
    "generic_region": Template(
        "${time_range}年，${geo_object_id}区域内${variable}${statistic}为${value}${unit}"
        "（来源：${source_table}）。"
    ),

    # ── 解释类 (interpretation) ──
    "interpret_trend": Template(
        "${time_range}期间，${geo_object_id}的${variable}呈${direction}趋势"
        "（从${start_value}${unit}到${end_value}${unit}，变化${change_value}${unit}）。"
    ),
    "interpret_heterogeneity": Template(
        "${time_range}年，${geo_object_id}的${variable}空间异质性可由变异系数（cv=${cv}）"
        "和标准差（std=${std}${unit}）描述。${cv_interpretation}。"
    ),

    # ── 对比类 (comparative) ──
    "compare_two_objects": Template(
        "${time_range}年，${geo_a}的${variable} ${statistic}（${value_a}${unit}）"
        "${relation}${geo_b}（${value_b}${unit}），"
        "差异为${diff}${unit}（${diff_pct}%）。"
    ),
    "compare_two_periods": Template(
        "${geo_object_id}的${variable}在${period_a}年为${value_a}${unit}，"
        "${period_b}年变为${value_b}${unit}，"
        "变化${change}${unit}。"
    ),

    # ── 方法类 (method) ──
    "method_zonal_stats": Template(
        "${variable}的统计值通过分区统计（zonal statistics）获得："
        "以${boundary_source}为统计单元边界，从${raster_source}栅格中"
        "提取覆盖范围内的所有像元值，计算${stats_list}等统计量。"
    ),

    # ── 不确定性类 (uncertainty) ──
    "uncertainty_note": Template(
        "${geo_object_id}的${variable} ${statistic}值为${value}${unit}，"
        "基于${sample_size}个像元（${spatial_support}空间支撑）。"
        "需要注意${note}。"
    ),

    # ── 人文地理类 (human geography) ──
    "hg_stat": Template(
        "${time_range}年，${geo_object_id}的${variable}为${value}${unit}"
        "（来源：${source_table}）。"
    ),
    "hg_compare_regions": Template(
        "${time_range}年，${geo_a}的${variable}（${value_a}${unit}）"
        "${relation}${geo_b}（${value_b}${unit}），"
        "前者是后者的${ratio}倍。"
    ),
    "hg_structure": Template(
        "${time_range}年，${geo_object_id}的${variable}构成中，"
        "${primary_type}占比${primary_pct}%，${secondary_type}占比${secondary_pct}%。"
    ),

    # ── 水文类 (hydrology) ──
    "hydro_discharge": Template(
        "${time_range}年，${geo_object_id}的${variable}为${value}${unit}"
        "（来源：${source_table}）。"
    ),
    "hydro_flow_direction": Template(
        "${geo_object_id}的流向为${direction}，汇入${downstream}"
        "（来源：${source_table}）。"
    ),

    # ── 气候类 (climate) ──
    "climate_stat": Template(
        "${time_range}年，${geo_object_id}的${variable} ${statistic}为${value}${unit}"
        "（来源：${source_table}）。"
    ),
    "climate_trend": Template(
        "${time_range}期间，${geo_object_id}的${variable}${statistic}呈${trend}趋势"
        "，变化速率为${rate}${unit}/年（来源：${source_table}）。"
    ),

    # ── 生态类 (ecology) ──
    "ecology_index": Template(
        "${time_range}年，${geo_object_id}的${variable}为${value}"
        "（来源：${source_table}）。"
    ),

    # ── 灾害类 (hazard) ──
    "hazard_event": Template(
        "${time_range}，${geo_object_id}发生${event_type}，"
        "影响范围${affected_area}${unit}，强度${magnitude}"
        "（来源：${source_table}）。"
    ),

    # ── 空间自相关 (spatial autocorrelation) ──
    "spatial_autocorr": Template(
        "${geo_object_id}的${variable}空间自相关Moran's I为${moran_i}"
        "（p=${p_value}），表明空间分布呈${pattern}模式"
        "（来源：${source_table}）。"
    ),

    # ── 地形分析 (terrain) ──
    "terrain_slope": Template(
        "${geo_object_id}的平均坡度为${slope_mean}°，最大坡度${slope_max}°，"
        "坡向以${aspect_dominant}为主（来源：${source_table}）。"
    ),
    "terrain_relief": Template(
        "${geo_object_id}的地形起伏度为${relief}${unit}"
        "（max-min=${max_ele}${unit}-${min_ele}${unit}），"
        "属于${relief_class}（来源：${source_table}）。"
    ),

    # ── 线矢量 (line features: rivers, roads, faults) ──
    "line_feature": Template(
        "${geo_object_id}（${name}）为${feature_type}，"
        "长度${length}${unit}（来源：${source_table}）。"
    ),
    "line_network": Template(
        "${geo_object_id}连接${from_node}至${to_node}，"
        "${variable}为${value}${unit}（来源：${source_table}）。"
    ),

    # ── 跨界关联 (cross-variable correlation) ──
    "cross_var_correlation": Template(
        "${time_range}年，${geo_object_id}的${var_a}与${var_b}"
        "${correlation_direction}相关（r=${correlation_r}），"
        "表明${interpretation}（来源：${source_table}）。"
    ),
}

DEFAULT_TEMPLATES = {
    "glacier_thickness_change": Template(
        "在${time_range}期间，冰川${glacier_id}的${variable}"
        "${statistic}为${value}${unit}"
        "（来源：${source_table}）。"
    ),
    "glacier_thinning_rate": Template(
        "冰川${glacier_id}在${time_range}期间的${variable}为"
        "${value}${unit}。"
    ),
    "region_summary": Template(
        "在${time_range}期间，${region_id}区域内冰川平均${variable}"
        "为${value}${unit}，变异系数为${cv}。"
    ),
    "glacier_yearly_thickness": Template(
        "${year}年，冰川${glacier_id}的平均${variable}为"
        "${value}${unit}。"
    ),
    "glacier_area_change": Template(
        "冰川${glacier_id}的面积从${start_year}年到${end_year}年"
        "变化了${value}${unit}。"
    ),
    "neighbor_similarity": Template(
        "冰川${glacier_id}与其最近邻冰川${neighbor_id}在${variable}上的"
        "空间依赖性由距离${distance_m}米和权重${weight}描述。"
    ),
}


class TemplateRenderer:
    """Renders templates into natural-language statements using data context."""

    def __init__(self, templates_dir: Path | None = None):
        self.templates: dict[str, Template] = {}
        self.templates.update(GENERIC_TEMPLATES)
        self.templates.update(DEFAULT_TEMPLATES)
        if templates_dir and templates_dir.exists():
            self._load_custom_templates(templates_dir)

    def _load_custom_templates(self, templates_dir: Path) -> None:
        for f in templates_dir.glob("*.txt"):
            name = f.stem
            text = f.read_text(encoding="utf-8")
            self.templates[name] = Template(text)

    def render(self, template_name: str, context: dict) -> str:
        """Render a named template with the given context.

        Args:
            template_name: Name of template to use (built-in or custom).
            context: Dict of values to substitute into template placeholders.
        """
        if template_name in self.templates:
            tmpl = self.templates[template_name]
        else:
            # Detect if it's a change/trend or a static stat
            if any(k in template_name.lower() for k in ("change", "trend", "rate", "diff")):
                tmpl = GENERIC_TEMPLATES["generic_change"]
            else:
                tmpl = GENERIC_TEMPLATES["generic_stat"]
        return tmpl.safe_substitute(context)

    def list_templates(self) -> list[str]:
        return sorted(self.templates.keys())
